# GBDK-2020 toolchain used by the Makefile when GBDK_HOME is not set.
#   make image     (builds this as "gbdk-dev")
FROM ubuntu:24.04

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gcc make python3 \
 && rm -rf /var/lib/apt/lists/*

# The release tarballs are per-architecture and this gets built on Apple
# silicon as often as on x86 -- hardcoding linux64 gives an aarch64 container
# x86_64 binaries that will not run.
ARG GBDK_VERSION=4.5.0
RUN set -e; \
    case "$(uname -m)" in \
      x86_64)  GBDK_ARCH=linux64 ;; \
      aarch64) GBDK_ARCH=linux-arm64 ;; \
      *) echo "gbdk: unsupported arch $(uname -m)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/gbdk.tar.gz \
      "https://github.com/gbdk-2020/gbdk-2020/releases/download/${GBDK_VERSION}/gbdk-${GBDK_ARCH}.tar.gz" \
 && mkdir -p /opt && tar -xzf /tmp/gbdk.tar.gz -C /opt \
 && rm /tmp/gbdk.tar.gz

ENV GBDK_HOME=/opt/gbdk
ENV PATH="/opt/gbdk/bin:${PATH}"
WORKDIR /work
