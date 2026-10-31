FROM node:22-slim AS build

WORKDIR /app
COPY packages/client/package.json packages/client/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY packages/client/ ./
ARG VITE_PUBLIC_BACKEND_URL=http://localhost:8000
ENV VITE_PUBLIC_BACKEND_URL=$VITE_PUBLIC_BACKEND_URL
RUN npm run build

FROM node:22-slim

WORKDIR /app
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/index.html ./index.html
COPY --from=build /app/plugins ./plugins
COPY --from=build /app/kernel ./kernel
COPY --from=build /app/shell ./shell
COPY --from=build /app/legacy ./legacy
COPY --from=build /app/vite.config.ts ./vite.config.ts
COPY --from=build /app/vite-plugin-client-modules.ts ./vite-plugin-client-modules.ts
COPY --from=build /app/tsconfig.json ./tsconfig.json

ENV BACKEND_URL=http://backend:8000
EXPOSE 4000
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "4000"]
