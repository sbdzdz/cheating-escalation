FROM node:24.14.0-bookworm-slim AS harness-build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY source.json /tmp/source.json
RUN node -e 'const {execFileSync:e}=require("node:child_process"),s=require("/tmp/source.json");e("git",["init","/src"]);e("git",["-C","/src","fetch","--depth=1",s.repository,s.commit]);e("git",["-C","/src","checkout","--detach","FETCH_HEAD"]);'
WORKDIR /src
ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1 HUSKY=0
RUN corepack enable && corepack prepare pnpm@10.33.2 --activate
RUN pnpm install --frozen-lockfile --ignore-scripts --filter @zcode/cli...
RUN ZCODE_ENV=production pnpm --filter @zcode/cli... -r run build
RUN node apps/zcode-cli/packages/cli/dist/zcode.cjs --version

FROM harness-build AS node-runtime
# TASK_BASE
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=harness-build /src/apps/zcode-cli/packages/cli/dist /opt/zcode/
COPY runtime.json /opt/factorization-runtime.json
RUN node /opt/zcode/zcode.cjs --version
WORKDIR /workspace
