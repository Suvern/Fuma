FROM node:22-bookworm-slim AS build
RUN npm install --global pnpm@12.4.1
WORKDIR /app/frontend
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
COPY scripts/license-policy.json /app/scripts/license-policy.json
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM caddy:2-alpine
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/licenses/fuma/
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/frontend/dist /srv/fuma
EXPOSE 80
