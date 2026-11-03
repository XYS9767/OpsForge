FROM golang:1.27.3-bookworm AS go
FROM docker:27-dind@sha256:aa3df78ecf320f5fafdce71c659f1629e96e9de0968305fe1de670e0ca9176ce AS docker-cli
FROM debian:bookworm-slim
ARG TARGETARCH=amd64
ARG KUBECTL_VERSION=v1.34.1
ARG HELM_VERSION=v3.18.6
ARG KUBEBUILDER_VERSION=v4.9.0
ARG PROMETHEUS_VERSION=3.5.0
ARG ALERTMANAGER_VERSION=0.28.1
ARG NODE_EXPORTER_VERSION=1.9.1
ARG TERRAFORM_VERSION=1.13.5
ARG TERRAFORM_LOCAL_VERSION=2.5.3
ARG TRAEFIK_VERSION=3.5.4
ARG ENVTEST_VERSION=1.34.1
ARG MYSQL_NATIVE_VERSION=8.4.13
ARG COMPOSE_VERSION=5.1.4
ARG REDIS_COMMIT=9913c926510755fa0d241658f550338a02258edb
ENV PATH=/usr/local/go/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/workspace OPSFORGE_TF_PROVIDER_MIRROR=/opt/terraform-providers
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 0755 /usr/sbin/policy-rc.d \
    && apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl bash python3 python3-pip python3-venv python3-yaml python3-pymysql python3-cryptography ansible openssh-client openssl \
    git make gcc libc6-dev jq procps lsof iproute2 dnsutils bind9-utils iputils-ping net-tools tcpdump acl util-linux fdisk e2fsprogs \
    vim-tiny gawk sed findutils coreutils tar gzip xz-utils libaio1 libnuma1 docker.io redis-tools default-mysql-client nginx-light libnginx-mod-stream haproxy bird2 keepalived \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -c 'import subprocess; flags=subprocess.run(["nginx","-V"],check=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=5).stdout.split(); required=["--with-http_v2_module","--with-http_secure_link_module","--with-http_slice_module"]; assert all(flag in flags for flag in required), "Nginx lab modules unavailable"; output=subprocess.check_output(["curl","-V"],text=True,timeout=5); assert any(line.startswith("Features:") and "HTTP2" in line.split()[1:] for line in output.splitlines()), "curl HTTP2 unavailable"'
COPY --from=go /usr/local/go /usr/local/go
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
RUN set -eu; \
    test "$REDIS_COMMIT" = 9913c926510755fa0d241658f550338a02258edb; \
    mkdir -p /tmp/lab-redis; cd /tmp/lab-redis; \
    curl -fsSL --retry 3 -A OpsForge-local-validation -o redis.tar.gz "https://api.github.com/repos/redis/redis/tarball/${REDIS_COMMIT}"; \
    printf '%s  %s\n' '7795a349d192072b7a817fe173dd3ba7bb45e473cfbb268ad2551f97c3856130' redis.tar.gz | sha256sum -c -; \
    tar -xzf redis.tar.gz --strip-components=1; \
    make -j1 MALLOC=libc BUILD_TLS=no OPTIMIZATION='-O2' REDIS_CFLAGS='' REDIS_LDFLAGS='' redis-server redis-cli; \
    install -m 0755 src/redis-server src/redis-cli /usr/local/bin/; \
    redis-server --version; redis-cli --version; cd /; rm -rf /tmp/lab-redis
RUN set -eu; \
    test "$COMPOSE_VERSION" = 5.1.4; \
    case "$TARGETARCH" in \
      amd64) platform=x86_64; digest=33b208d7e76639db742fae84b966cc01dacae58ca3fc4dabbc907045aefdf0c4;; \
      arm64) platform=aarch64; digest=d4fb48b72857810314d3ee77123c89954101844efa4788031221f4c370495946;; \
      *) echo "Unsupported Compose architecture: $TARGETARCH" >&2; exit 1;; \
    esac; \
    curl -fsSL --retry 3 -o /tmp/docker-compose "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${platform}"; \
    printf '%s  %s\n' "$digest" /tmp/docker-compose | sha256sum -c -; \
    install -m 0755 /tmp/docker-compose /usr/local/bin/docker-compose; \
    docker-compose version --short; rm /tmp/docker-compose
RUN set -eu; \
    if [ "$TARGETARCH" = amd64 ]; then \
      test "$MYSQL_NATIVE_VERSION" = 8.4.13; \
      archive="mysql-${MYSQL_NATIVE_VERSION}-linux-glibc2.28-x86_64-minimal.tar.xz"; \
      mkdir -p /tmp/lab-mysql /opt/opsforge-mysql; cd /tmp/lab-mysql; \
      curl -fsSL --retry 3 -o "$archive" "https://cdn.mysql.com/Downloads/MySQL-8.4/$archive"; \
      printf '%s  %s\n' '5dfbb764f731df40ef9e4f5d69aed32bdac8ba1af20bd96b7d40a942d83d4ed2' "$archive" | sha256sum -c -; \
      tar -xJf "$archive" --strip-components=1 -C /opt/opsforge-mysql; \
      ln -s /opt/opsforge-mysql/bin/mysqld /usr/local/bin/mysqld; \
      mysqld --no-defaults --version; cd /; rm -rf /tmp/lab-mysql; \
    else \
      printf '%s\n' 'Native MySQL 8.4 exercises are bundled for amd64 only; capability checks reject these exercises on this image architecture.'; \
    fi
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) digest=c8500090806ed5ce4064eeeb2a5666476a5168c1f4ff0eadd54fe59b22c4baa7;; \
      arm64) digest=cb56759108ea15933abf79d8573bbf66cca8c13e20425d7bc9f95941a060649d;; \
      *) echo "Unsupported envtest architecture: $TARGETARCH" >&2; exit 1;; \
    esac; \
    test "$ENVTEST_VERSION" = 1.34.1; \
    archive="envtest-v${ENVTEST_VERSION}-linux-${TARGETARCH}.tar.gz"; \
    mkdir -p /tmp/lab-envtest; cd /tmp/lab-envtest; \
    curl -fsSL --retry 3 -o "$archive" "https://github.com/kubernetes-sigs/controller-tools/releases/download/envtest-v${ENVTEST_VERSION}/$archive"; \
    printf '%s  %s\n' "$digest" "$archive" | sha256sum -c -; \
    tar -xzf "$archive" controller-tools/envtest/kube-apiserver controller-tools/envtest/etcd; \
    install -m 0755 controller-tools/envtest/kube-apiserver controller-tools/envtest/etcd /usr/local/bin/; \
    kube-apiserver --version; etcd --version; cd /; rm -rf /tmp/lab-envtest
RUN set -eu; \
    case "$TARGETARCH" in amd64|arm64) ;; *) echo "Unsupported lab architecture: $TARGETARCH" >&2; exit 1;; esac; \
    archive="traefik_v${TRAEFIK_VERSION}_linux_${TARGETARCH}.tar.gz"; \
    url="https://github.com/traefik/traefik/releases/download/v${TRAEFIK_VERSION}"; \
    mkdir -p /tmp/lab-traefik; cd /tmp/lab-traefik; \
    curl -fsSL --retry 3 -o "$archive" "$url/$archive"; \
    curl -fsSL --retry 3 -o sums.txt "$url/traefik_v${TRAEFIK_VERSION}_checksums.txt"; \
    awk -v name="$archive" '$2 == name {print; found=1} END {if (!found) exit 1}' sums.txt > selected.sha256; \
    sha256sum -c selected.sha256; \
    tar -xzf "$archive" traefik; install -m 0755 traefik /usr/local/bin/traefik; \
    traefik version; cd /; rm -rf /tmp/lab-traefik
RUN set -eu; \
    case "$TARGETARCH" in amd64|arm64) ;; *) echo "Unsupported lab architecture: $TARGETARCH" >&2; exit 1;; esac; \
    for component in prometheus alertmanager node_exporter; do \
      case "$component" in prometheus) version="$PROMETHEUS_VERSION"; binary=promtool;; alertmanager) version="$ALERTMANAGER_VERSION"; binary=amtool;; node_exporter) version="$NODE_EXPORTER_VERSION"; binary=node_exporter;; esac; \
      archive="${component}-${version}.linux-${TARGETARCH}.tar.gz"; \
      url="https://github.com/prometheus/${component}/releases/download/v${version}"; \
      mkdir -p /tmp/lab-tools; \
      curl -fsSL --retry 3 -o "/tmp/lab-tools/$archive" "$url/$archive"; \
      curl -fsSL --retry 3 -o /tmp/lab-tools/sha256sums.txt "$url/sha256sums.txt"; \
      cd /tmp/lab-tools; \
      awk -v name="$archive" '$2 == name {print; found=1} END {if (!found) exit 1}' sha256sums.txt > selected.sha256; \
      sha256sum -c selected.sha256; \
      for executable in "$binary" "$component"; do \
        tar -xzf "$archive" "${component}-${version}.linux-${TARGETARCH}/$executable"; \
        install -m 0755 "${component}-${version}.linux-${TARGETARCH}/$executable" "/usr/local/bin/$executable"; \
      done; \
      cd /; rm -rf /tmp/lab-tools; \
    done
RUN set -eu; \
    archive="terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip"; \
    url="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}"; \
    mkdir -p /tmp/lab-terraform; cd /tmp/lab-terraform; \
    curl -fsSL --retry 3 -o "$archive" "$url/$archive"; \
    curl -fsSL --retry 3 -o sums.txt "$url/terraform_${TERRAFORM_VERSION}_SHA256SUMS"; \
    awk -v name="$archive" '$2 == name {print; found=1} END {if (!found) exit 1}' sums.txt > selected.sha256; \
    sha256sum -c selected.sha256; \
    python3 -c 'import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extract("terraform", ".")' "$archive"; \
    install -m 0755 terraform /usr/local/bin/terraform; \
    cd /; rm -rf /tmp/lab-terraform
RUN set -eu; \
    archive="terraform-provider-local_${TERRAFORM_LOCAL_VERSION}_linux_${TARGETARCH}.zip"; \
    url="https://releases.hashicorp.com/terraform-provider-local/${TERRAFORM_LOCAL_VERSION}"; \
    mkdir -p /tmp/lab-local-provider; cd /tmp/lab-local-provider; \
    curl -fsSL --retry 3 -o "$archive" "$url/$archive"; \
    curl -fsSL --retry 3 -o sums.txt "$url/terraform-provider-local_${TERRAFORM_LOCAL_VERSION}_SHA256SUMS"; \
    awk -v name="$archive" '$2 == name {print; found=1} END {if (!found) exit 1}' sums.txt > selected.sha256; \
    sha256sum -c selected.sha256; \
    python3 -c 'import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); names=[n for n in z.namelist() if "/" not in n and n.startswith("terraform-provider-local_v")]; assert len(names)==1; z.extract(names[0], ".")' "$archive"; \
    destination="/opt/terraform-providers/registry.terraform.io/hashicorp/local/${TERRAFORM_LOCAL_VERSION}/linux_${TARGETARCH}"; \
    mkdir -p "$destination"; install -m 0755 terraform-provider-local_v* "$destination/"; \
    cd /; rm -rf /tmp/lab-local-provider
RUN curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
    && curl -fsSLo /tmp/kubectl.sha256 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl.sha256" \
    && cd /tmp && echo "$(cat kubectl.sha256)  kubectl" | sha256sum -c - \
    && install -m 0755 /tmp/kubectl /usr/local/bin/kubectl \
    && curl -fsSLo /tmp/helm.tar.gz "https://get.helm.sh/helm-${HELM_VERSION}-linux-${TARGETARCH}.tar.gz" \
    && curl -fsSLo /tmp/helm.sha256 "https://get.helm.sh/helm-${HELM_VERSION}-linux-${TARGETARCH}.tar.gz.sha256sum" \
    && cd /tmp && sed "s@helm-${HELM_VERSION}-linux-${TARGETARCH}.tar.gz@helm.tar.gz@" helm.sha256 | sha256sum -c - \
    && tar -xzf /tmp/helm.tar.gz -C /tmp && install -m 0755 "/tmp/linux-${TARGETARCH}/helm" /usr/local/bin/helm \
    && curl -fsSLo /usr/local/bin/kubebuilder "https://github.com/kubernetes-sigs/kubebuilder/releases/download/${KUBEBUILDER_VERSION}/kubebuilder_linux_${TARGETARCH}" \
    && chmod 0755 /usr/local/bin/kubebuilder \
    && rm -rf /tmp/* \
    && useradd --uid 1000 --create-home student
COPY setup-workspace /usr/local/bin/setup-workspace
RUN chmod 0755 /usr/local/bin/setup-workspace \
    && bash -n /usr/local/bin/setup-workspace \
    && python3 -c 'import ast,pathlib; lines=pathlib.Path("/usr/local/bin/setup-workspace").read_text().splitlines(); start=next(i for i,line in enumerate(lines) if line.startswith("python3 - <<")); end=lines.index("PY",start+1); ast.parse("\n".join(lines[start+1:end]))'
USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/setup-workspace"]
