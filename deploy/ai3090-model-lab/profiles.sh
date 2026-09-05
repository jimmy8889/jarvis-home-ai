#!/usr/bin/env bash
# Shared, intentionally explicit profiles for the single-GPU ai3090 model lab.

MODEL_LAB_ROOT="${MODEL_LAB_ROOT:-$HOME/pilot-model-lab}"
MODEL_LAB_BIN="${MODEL_LAB_BIN:-$MODEL_LAB_ROOT/bin/llama-server}"
MODEL_LAB_PORT="${MODEL_LAB_PORT:-8081}"
MODEL_LAB_HOST="${MODEL_LAB_HOST:-127.0.0.1}"

model_lab_profile() {
  local profile="$1"
  MODEL_LAB_PROFILE="$profile"
  MODEL_LAB_CONTEXT=16384
  MODEL_LAB_MODEL=""
  MODEL_LAB_EXPECTED_BYTES=0
  case "$profile" in
    fast)
      MODEL_LAB_MODEL="$MODEL_LAB_ROOT/models/qwen35/Qwen3.5-9B-The-Defiant-Fable-Uncnr-Heretic-NEO-MAX-MTP-Q4_K_M.gguf"
      MODEL_LAB_EXPECTED_BYTES=6979975392
      ;;
    quality)
      MODEL_LAB_MODEL="$MODEL_LAB_ROOT/models/qwen36/Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-MTP-Q4_K_M.gguf"
      MODEL_LAB_EXPECTED_BYTES=18498575840
      ;;
    agent-iq4-xs)
      MODEL_LAB_CONTEXT=8192
      MODEL_LAB_MODEL="$MODEL_LAB_ROOT/models/qwen36-35b/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"
      MODEL_LAB_EXPECTED_BYTES=18209036576
      ;;
    agent-iq4-nl)
      MODEL_LAB_CONTEXT=8192
      MODEL_LAB_MODEL="$MODEL_LAB_ROOT/models/qwen36-35b/Qwen3.6-35B-A3B-UD-IQ4_NL.gguf"
      MODEL_LAB_EXPECTED_BYTES=18536192288
      ;;
    *)
      echo "Unknown profile: $profile (fast, quality, agent-iq4-xs, agent-iq4-nl)" >&2
      return 2
      ;;
  esac
}
