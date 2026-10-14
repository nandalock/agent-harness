FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

WORKDIR /app

# HuggingFace 走国内镜像（构建时预下载 reranker 模型用）
ENV HF_ENDPOINT=https://hf-mirror.com
# pip 走清华镜像（加速依赖安装）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# Node.js + npm (for npx MCP servers)
ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn
RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources && \
    printf 'Acquire::Retries "3";\n' > /etc/apt/apt.conf.d/80-retries && \
    apt-get update && apt-get install -y curl gnupg && \
    curl --retry 3 --retry-delay 2 -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# uv (for uvx MCP servers)
RUN pip install --upgrade pip uv

# CPU wheel pinned to the official CDN and its SHA256 (Python 3.12 / amd64).
# The R2 download endpoint can return an incomplete file on this network.
ARG TORCH_WHEEL_URL=https://download.pytorch.org/whl/cpu/torch-2.14.1%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl#sha256=5a6363570c753812540a05eb82380e329469cbe668643e88111414c12627711f
RUN pip install --no-cache-dir "${TORCH_WHEEL_URL}" --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    fastapi uvicorn pyjwt psycopg2-binary pydantic python-multipart \
    websockets aiohttp requests sentence-transformers \
    langchain-core langchain-openai langgraph 'mcp<2' redis numpy pypdf 'PyYAML>=6,<7' python-dotenv

# RAG downloads the reranker on first use; deployment can opt into preloading.
ARG PRELOAD_RERANKER=false
RUN if [ "$PRELOAD_RERANKER" = "true" ]; then \
        python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"; \
    fi

# docker CLI（沙箱执行器起临时容器用；只装客户端，不装 daemon）。
# 放在重依赖之后，避免改动它使 torch / 模型下载层缓存失效。
# 走阿里云镜像：download.docker.com 在墙内常不可达。
ARG DOCKER_CLI_VERSION=27.3.1
RUN curl --retry 3 --retry-delay 2 -fsSL "https://mirrors.aliyun.com/docker-ce/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
    | tar -xz --strip-components=1 -C /usr/local/bin docker/docker && \
    docker --version

RUN npm install --global overleaf-mcp-rt@2.2.0

COPY . ./backend

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
