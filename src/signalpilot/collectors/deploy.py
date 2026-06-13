"""Deployment change collector – diffs the two most recent ReplicaSet revisions."""

from __future__ import annotations

from typing import Optional

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from signalpilot.collectors.kube_api import _load_kube_config, _parse_ts
from signalpilot.models import DeployChange, ImageDiff, ResourceDiff

_SENSITIVE_ENV_PATTERNS = {"PASSWORD", "TOKEN", "SECRET", "API_KEY", "APIKEY"}


def _mask_env_value(name: str, value: Optional[str]) -> Optional[str]:
    upper = name.upper()
    if any(pat in upper for pat in _SENSITIVE_ENV_PATTERNS):
        return "[REDACTED]"
    return value


def _get_env_map(containers, masked: bool = False) -> dict[str, Optional[str]]:
    """Return {env_name: value} for all containers.

    When *masked* is True, sensitive values are replaced with ``[REDACTED]``.
    """
    result: dict[str, Optional[str]] = {}
    for container in containers or []:
        for env in getattr(container, "env", None) or []:
            value = getattr(env, "value", None)
            result[env.name] = _mask_env_value(env.name, value) if masked else value
    return result


def _diff_images(prev_containers, curr_containers) -> list[ImageDiff]:
    prev_map = {c.name: getattr(c, "image", "") or "" for c in (prev_containers or [])}
    curr_map = {c.name: getattr(c, "image", "") or "" for c in (curr_containers or [])}
    diffs: list[ImageDiff] = []
    for name, curr_image in curr_map.items():
        prev_image = prev_map.get(name)
        if prev_image == curr_image:
            continue
        prev_tag = prev_image.split(":")[-1] if prev_image else None
        curr_tag = curr_image.split(":")[-1] if curr_image else ""
        tag_changed = prev_tag != curr_tag
        # Digest change: images differ but may share same tag
        digest_changed = prev_image != curr_image
        diffs.append(
            ImageDiff(
                from_image=prev_image or None,
                to_image=curr_image,
                tag_changed=tag_changed,
                digest_changed=digest_changed,
            )
        )
    return diffs


def _diff_env(prev_containers, curr_containers) -> dict[str, tuple[Optional[str], Optional[str]]]:
    # Compare using raw (unmasked) values to detect changes,
    # but report using masked values to avoid leaking secrets.
    prev_raw = _get_env_map(prev_containers, masked=False)
    curr_raw = _get_env_map(curr_containers, masked=False)
    prev_masked = _get_env_map(prev_containers, masked=True)
    curr_masked = _get_env_map(curr_containers, masked=True)
    diff: dict[str, tuple[Optional[str], Optional[str]]] = {}
    for key in set(prev_raw) | set(curr_raw):
        if prev_raw.get(key) != curr_raw.get(key):
            diff[key] = (prev_masked.get(key), curr_masked.get(key))
    return diff


def _get_resource(container, field: str, resource_type: str) -> Optional[str]:
    resources = getattr(container, "resources", None)
    if not resources:
        return None
    bucket = getattr(resources, resource_type, None)
    if not bucket:
        return None
    if isinstance(bucket, dict):
        return bucket.get(field)
    return getattr(bucket, field, None)


def _diff_resources(prev_containers, curr_containers) -> list[ResourceDiff]:
    prev_map = {c.name: c for c in (prev_containers or [])}
    curr_map = {c.name: c for c in (curr_containers or [])}
    diffs: list[ResourceDiff] = []
    for name, curr_c in curr_map.items():
        prev_c = prev_map.get(name)
        rd = ResourceDiff(
            container=name,
            from_cpu_request=_get_resource(prev_c, "cpu", "requests") if prev_c else None,
            to_cpu_request=_get_resource(curr_c, "cpu", "requests"),
            from_cpu_limit=_get_resource(prev_c, "cpu", "limits") if prev_c else None,
            to_cpu_limit=_get_resource(curr_c, "cpu", "limits"),
            from_mem_request=_get_resource(prev_c, "memory", "requests") if prev_c else None,
            to_mem_request=_get_resource(curr_c, "memory", "requests"),
            from_mem_limit=_get_resource(prev_c, "memory", "limits") if prev_c else None,
            to_mem_limit=_get_resource(curr_c, "memory", "limits"),
        )
        # Only include if something actually changed
        if (
            rd.from_cpu_request != rd.to_cpu_request
            or rd.from_cpu_limit != rd.to_cpu_limit
            or rd.from_mem_request != rd.to_mem_request
            or rd.from_mem_limit != rd.to_mem_limit
        ):
            diffs.append(rd)
    return diffs


def _diff_config_refs(prev_containers, curr_containers) -> list[str]:
    """Return list of configmap/secret ref names that changed."""

    def collect_refs(containers) -> set[str]:
        refs: set[str] = set()
        for c in containers or []:
            for env in getattr(c, "env", None) or []:
                vf = getattr(env, "value_from", None)
                if vf:
                    cm = getattr(vf, "config_map_key_ref", None)
                    sec = getattr(vf, "secret_key_ref", None)
                    if cm:
                        refs.add(f"configmap:{getattr(cm, 'name', '')}")
                    if sec:
                        refs.add(f"secret:{getattr(sec, 'name', '')}")
            for env_from in getattr(c, "env_from", None) or []:
                cm = getattr(env_from, "config_map_ref", None)
                sec = getattr(env_from, "secret_ref", None)
                if cm:
                    refs.add(f"configmap:{getattr(cm, 'name', '')}")
                if sec:
                    refs.add(f"secret:{getattr(sec, 'name', '')}")
        return refs

    prev_refs = collect_refs(prev_containers)
    curr_refs = collect_refs(curr_containers)
    return sorted((prev_refs ^ curr_refs))


def get_deploy_change(
    namespace: str,
    deployment: str,
    settings=None,
) -> Optional[DeployChange]:
    """Return the most recent DeployChange for *deployment* in *namespace*.

    Returns None if the deployment is not found or has fewer than two
    recorded ReplicaSet revisions.
    """
    _load_kube_config(settings)
    apps_api = client.AppsV1Api()

    try:
        apps_api.read_namespaced_deployment(name=deployment, namespace=namespace)
    except ApiException:
        return None

    rs_list = apps_api.list_namespaced_replica_set(namespace=namespace)

    # Collect replicasets owned by this deployment that have a revision annotation
    owned: list[tuple[int, object]] = []
    for rs in rs_list.items:
        owner_refs = getattr(rs.metadata, "owner_references", None) or []
        for ref in owner_refs:
            if getattr(ref, "kind", "") == "Deployment" and getattr(ref, "name", "") == deployment:
                annotations = getattr(rs.metadata, "annotations", None) or {}
                if isinstance(annotations, dict):
                    rev_str = annotations.get("deployment.kubernetes.io/revision")
                else:
                    rev_str = getattr(annotations, "deployment.kubernetes.io/revision", None)
                if rev_str:
                    owned.append((int(rev_str), rs))
                break

    if len(owned) < 2:
        return None

    owned.sort(key=lambda x: x[0])
    prev_rev, prev_rs = owned[-2]
    curr_rev, curr_rs = owned[-1]

    prev_containers = (
        prev_rs.spec.template.spec.containers
        if (prev_rs.spec and prev_rs.spec.template and prev_rs.spec.template.spec)
        else []
    )
    curr_containers = (
        curr_rs.spec.template.spec.containers
        if (curr_rs.spec and curr_rs.spec.template and curr_rs.spec.template.spec)
        else []
    )

    deploy_time = _parse_ts(getattr(curr_rs.metadata, "creation_timestamp", None))
    prev_replicas = getattr(prev_rs.spec, "replicas", None) or 0
    curr_replicas = getattr(curr_rs.spec, "replicas", None) or 0

    return DeployChange(
        deployment=deployment,
        namespace=namespace,
        from_revision=str(prev_rev),
        to_revision=str(curr_rev),
        deploy_time=deploy_time,
        image_diffs=_diff_images(prev_containers, curr_containers),
        env_diff=_diff_env(prev_containers, curr_containers),
        resource_diffs=_diff_resources(prev_containers, curr_containers),
        config_ref_changes=_diff_config_refs(prev_containers, curr_containers),
        replica_diff=(prev_replicas, curr_replicas),
    )
