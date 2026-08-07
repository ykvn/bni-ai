"""
Shared CML model registry resolver.

Consolidates the repeated CML registry verification + HuggingFace
download fallback logic used by both embed_rerank and qwen_inference.
"""
from __future__ import annotations

import os
import sys
from typing import Tuple

import cmlapi
from huggingface_hub import snapshot_download


def _resolve_nfs_path(candidate_paths: list[str]) -> str | None:
    """Returns the first candidate path that contains a model config.json."""
    for p in candidate_paths:
        if os.path.isdir(p) and "config.json" in os.listdir(p):
            return p
    return None


def resolve_model_path(
    model_name: str,
    nfs_candidate_paths: list[str] | None = None,
) -> Tuple[str, str]:
    """
    Verifies the model in CML Registry and dynamically pulls the HuggingFace source.
    Falls back to direct HuggingFace download (or local NFS storage if paths provided).

    Args:
        model_name: The model name / repository ID.
        nfs_candidate_paths: Optional list of local disk paths to check for model
            weights before falling back to direct HuggingFace download.

    Returns a tuple of (resolved_path, source_label).
    """
    print(f"📡 [MODEL RESOLVER] Connecting to CML API to verify registry for '{model_name}'...")

    try:
        client = cmlapi.default_client()
        search_res = client.list_registered_models()
        models_list = getattr(search_res, 'models', getattr(search_res, 'registered_models', []))

        target_model = next(
            (m for m in models_list if getattr(m, 'name', getattr(m, 'model_name', '')) == model_name),
            None
        )

        if target_model:
            model_id = getattr(target_model, 'id', getattr(target_model, 'model_id', None))
            print(f"✅ [MODEL RESOLVER] Verified '{model_name}' (ID: {model_id}) exists in Cloudera AI Registry.")

            cache_dir = os.path.join(os.getcwd(), "hf_registry_cache", model_name.replace("/", "_"))
            os.makedirs(cache_dir, exist_ok=True)

            print(f"⏳ [MODEL RESOLVER] Downloading weights directly from HuggingFace Hub to mirror registry import...")
            downloaded_path = snapshot_download(
                repo_id=model_name,
                local_dir=cache_dir,
                local_dir_use_symlinks=False
            )

            print(f"🎉 [MODEL RESOLVER] Successfully pulled model artifacts: {downloaded_path}")
            return downloaded_path, "CLOUDERA_REGISTRY_HF_IMPORT"

        print(f"⚠️ Could not find '{model_name}' in the registry.")

    except Exception as err:
        print(f"⚠️ [MODEL RESOLVER] Verification error: {type(err).__name__} - {err}")

    # Fallback 1: Local NFS / disk storage (if candidate paths provided)
    if nfs_candidate_paths:
        print(f"🔍 [MODEL RESOLVER] Falling back to local NFS / disk storage...")
        local_path = _resolve_nfs_path(nfs_candidate_paths)
        if local_path:
            print(f"🎉 [MODEL RESOLVER] Found local model weights at: {local_path}")
            return local_path, "LOCAL_NFS_STORAGE"

        print(f"❌ [CRITICAL ERROR] Could not locate model weights in Registry OR local NFS paths.")
        sys.exit(1)

    # Fallback 2: Direct HuggingFace download (SentenceTransformers handles this natively)
    return model_name, "HUGGINGFACE_HUB_DIRECT"
