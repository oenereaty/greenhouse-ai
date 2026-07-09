# 빌드 스테이지 — 빌드 인자로 백엔드 절대 URL과 인증 키를 주입
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY . .
ARG VITE_API_BASE
ARG VITE_API_KEY
ENV VITE_API_BASE=${VITE_API_BASE}
ENV VITE_API_KEY=${VITE_API_KEY}
RUN npm run build

# 서빙 스테이지 — 정적 파일만 nginx로 서빙
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
