FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html style.css app.js /usr/share/nginx/html/
COPY modules /usr/share/nginx/html/modules
COPY vendor /usr/share/nginx/html/vendor
COPY source-assets /usr/share/nginx/html/source-assets
EXPOSE 8080
ENTRYPOINT ["nginx", "-g", "daemon off;"]
