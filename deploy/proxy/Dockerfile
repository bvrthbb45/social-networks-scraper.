# Builds the web app and serves it, plus the API under /api, over HTTPS. Build context: repository root.
FROM node:22-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY deploy/proxy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/proxy/api_proxy.conf /etc/nginx/api_proxy.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080 8443
