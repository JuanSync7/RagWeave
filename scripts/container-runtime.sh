#!/usr/bin/env bash
# @summary
# Detect container runtime: prefer Podman, fall back to Docker.
# Source this file — do not execute it directly.
#   source scripts/container-runtime.sh
# After sourcing, $CONTAINER_RT is set to "podman" or "docker".
# Exports: CONTAINER_RT
# Deps: podman or docker in PATH
# @end-summary

if command -v podman &>/dev/null; then
    CONTAINER_RT="podman"
elif command -v docker &>/dev/null; then
    CONTAINER_RT="docker"
else
    echo "Error: Neither podman nor docker found in PATH." >&2
    exit 1
fi
export CONTAINER_RT
