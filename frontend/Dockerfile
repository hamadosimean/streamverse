# Multi-stage: build the SPA with Vite, then serve the static bundle with Nginx.
# The edge Nginx (see ../nginx) reverse-proxies to this container for `/`.
FROM node:24-alpine AS build

WORKDIR /app

# Build-time config is baked into the bundle by Vite.
ARG VITE_API_BASE_URL=/api
ARG VITE_WS_BASE_URL=/ws
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_WS_BASE_URL=$VITE_WS_BASE_URL

COPY package.json package-lock.json* ./
# `npm ci` when a lockfile is present (reproducible), `npm install` on first run.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
RUN npm run build

FROM nginx:1.30-trixie AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
