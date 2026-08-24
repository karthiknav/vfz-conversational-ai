FROM nginx:1.27-alpine

COPY . /usr/share/nginx/html

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -q -O - http://localhost:80/ >/dev/null || exit 1

EXPOSE 80
