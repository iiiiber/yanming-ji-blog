# Docker 运维手册

> 适用环境：Ubuntu 24.04 LTS / Docker 26.1.4 / Compose v2.28.1 / overlay2 / cgroup2fs / systemd
> 编写日期：2026-06-10
> 适用服务器：124.223.155.35 (VM-0-5-ubuntu) 及同架构 CVM
> 维护：本机权威源，修改后同步飞书文档

---

## 0. 环境速查

```bash
# 一行总览
docker version --format '{{.Server.Version}} | {{.Client.Version}}' 2>&1
docker info --format '{{.Driver}} | {{.CgroupDriver}} | {{.CgroupVersion}} | {{.KernelVersion}}'
cat /etc/docker/daemon.json
```

本机当前配置：
- 存储驱动：`overlay2`
- Cgroup：`systemd` (cgroup v2)
- 根目录：`/var/lib/docker` （已用 2.2G）
- 注册表镜像：`mirror.ccs.tencentyun.com`、`docker.m.daocloud.io`
- 现有网络：`baota_net` (bridge)、默认 bridge/host/none
- 现有卷：1 个 local 卷
- 现有容器：1 个 mysql（`mysql_bptx-mysql_BpTX-1`，端口 13306→3306）

---

## 1. 安装与初始化

### 1.1 一键安装（Ubuntu/Debian）

```bash
# 官方脚本（国内可能慢）
curl -fsSL https://get.docker.com | bash

# 国内用户推荐用阿里云镜像
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh --mirror Aliyun

# 安装后把当前用户加进 docker 组（避免每次 sudo）
sudo usermod -aG docker $USER
newgrp docker   # 或重新登录

# 验证
docker run --rm hello-world
```

### 1.2 配置 daemon.json（最常改的）

```bash
# 标准位置
sudo nano /etc/docker/daemon.json
```

**推荐配置**（本机已用）：
```json
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.m.daocloud.io"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "5"
  },
  "storage-driver": "overlay2",
  "default-ulimits": {
    "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 }
  }
}
```

重启生效：
```bash
sudo systemctl restart docker
```

### 1.3 ⚠️ 改 daemon.json 的两个坑

| 现象 | 原因 | 修法 |
|------|------|------|
| `dockerd` 起不来：`invalid character '}' after array element` | 宝塔面板 / 其他工具会**自动注入** mirror，破坏 JSON 闭合 | 用 `python3 -c 'import json; json.dump(...)'` 写文件，**不要用 heredoc**；写完 `python3 -m json.tool` 校验 |
| 多次 `systemctl start docker` 失败 | systemd 限流（"Start request repeated too quickly"） | `systemctl reset-failed docker && systemctl start docker` |

### 1.4 镜像加速器选型（实测）

| Mirror | 实测结果 | 备注 |
|--------|---------|------|
| `mirror.ccs.tencentyun.com` | ✅ HTTP 200 | 腾讯云公网 mirror，**首选** |
| `docker.m.daocloud.io` | ✅ 通 | 备选 |
| `ccr.ccs.tencentyun.com` | ❌ 401 Unauthorized | 腾讯云**内网**，需账号授权 |
| `hub-mirror.c.163.com` | ❌ 000 域名失效 | 已下架 |
| `docker.mirrors.ustc.edu.cn` | ❌ 000 | 这台机不通 |
| `dockerproxy.com` | ❌ 000 | 这台机不通 |

---

## 2. 服务管理（systemd）

```bash
# 启停
sudo systemctl start docker
sudo systemctl stop docker
sudo systemctl restart docker

# 状态
sudo systemctl status docker
sudo systemctl is-active docker
sudo systemctl is-enabled docker

# 开机自启
sudo systemctl enable docker
sudo systemctl disable docker

# 限流重置（改坏配置反复启动会触发）
sudo systemctl reset-failed docker
sudo systemctl start docker

# 看日志（最后 50 条）
sudo journalctl -u docker -n 50 --no-pager
sudo journalctl -u docker -f   # 实时跟踪

# 看 dockerd 完整命令
systemctl cat docker | grep ExecStart
```

### 2.1 容器服务（开机自启）

```bash
# 临时容器重启策略
docker run --restart=no               myimage  # 默认：不重启
docker run --restart=on-failure:5     myimage  # 失败才重启，最多5次
docker run --restart=always           myimage  # 总是重启（包括 docker daemon 启动时）
docker run --restart=unless-stopped   myimage  # 推荐：除非手动 stop，否则总重启
```

```bash
# 已运行容器改重启策略
docker update --restart=unless-stopped <container>

# 批量改
docker ps -q | xargs -I {} docker update --restart=unless-stopped {}
```

---

## 3. 镜像管理

### 3.1 拉取 / 推送

```bash
docker pull mysql:8.0                       # 官方
docker pull registry.cn-hangzhou.aliyuncs.com/namespace/repo:tag   # 阿里云
docker pull mirror.ccs.tencentyun.com/library/mysql:8.0          # 走 mirror

# 推送（需先 docker login）
docker login
docker tag myapp:1.0 myregistry.com/myapp:1.0
docker push myregistry.com/myapp:1.0
```

### 3.2 列出 / 搜索 / 删除

```bash
docker images                              # 本地所有
docker images -a                           # 含中间层
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}'  # 精简

docker search nginx                        # Docker Hub 搜索
docker search --filter is-official=true nginx

# 删除
docker rmi <image>                         # 按 ID/name
docker rmi $(docker images -q -f "dangling=true")    # 清悬空镜像
docker image prune -a                      # 全部未用镜像（危险）
```

### 3.3 镜像标签 / 导出导入

```bash
# 打标签
docker tag mysql:8.0 myregistry.com/mysql:8.0

# 导出（生产环境离线迁移用）
docker save -o mysql-8.0.tar mysql:8.0
gzip mysql-8.0.tar                        # 压缩

# 导入
docker load -i mysql-8.0.tar
docker load -i mysql-8.0.tar.gz
```

### 3.4 构建镜像

```bash
# 标准构建
docker build -t myapp:1.0 .
docker build -t myapp:1.0 -f Dockerfile.dev .

# 多阶段构建指定阶段
docker build --target runtime -t myapp:runtime .

# 不用缓存
docker build --no-cache -t myapp:1.0 .

# BuildKit（更快，支持 secrets）
DOCKER_BUILDKIT=1 docker build -t myapp:1.0 .
```

Dockerfile 模板：
```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*
COPY . .
USER 1000:1000
EXPOSE 8000
CMD ["gunicorn", "app:app", "-b", "0.0.0.0:8000"]
```

### 3.5 查看镜像信息

```bash
docker history mysql:8.0                   # 层历史
docker inspect mysql:8.0                   # 完整 JSON
docker inspect --format='{{.Config.Env}}' mysql:8.0   # 环境变量
docker inspect --format='{{json .Config.ExposedPorts}}' mysql:8.0  # 端口
```

---

## 4. 容器生命周期

### 4.1 启动 / 停止 / 删除

```bash
# 运行
docker run -d --name web -p 8080:80 nginx:alpine
docker run -it --rm ubuntu:24.04 bash      # 交互式，用完即删
docker run -d --name db \
  -e MYSQL_ROOT_PASSWORD=*** \
  -v /data/mysql:/var/lib/mysql \
  -p 3306:3306 \
  --restart unless-stopped \
  mysql:8.0

# 查看
docker ps                 # 运行中
docker ps -a              # 全部
docker ps -q              # 只取 ID
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

# 启停
docker start <container>
docker stop <container>           # SIGTERM + 10s 超时
docker stop -t 30 <container>     # 给 30s 优雅退出
docker restart <container>
docker kill <container>           # SIGKILL 立即

# 删除
docker rm <container>
docker rm -f <container>          # 强制（运行中也能删）
docker rm $(docker ps -aq -f status=exited)   # 批量清已退出的
docker container prune            # 全部已停止
```

### 4.2 进入容器

```bash
docker exec -it <container> bash             # 首选 bash
docker exec -it <container> sh               # 镜像只有 sh 时（alpine）
docker exec -it -u root <container> bash     # 切到 root
docker exec -w /app <container> pwd          # 指定工作目录
docker exec <container> env                  # 不进 shell，直接看环境变量

# 单条命令
docker exec <container> cat /etc/nginx/nginx.conf > local.conf
```

### 4.3 查看日志

```bash
docker logs <container>                # 全部
docker logs --tail 100 <container>     # 最后 100 行
docker logs -f <container>             # 实时跟踪
docker logs --since 10m <container>    # 最近 10 分钟
docker logs --until 2026-06-10T08:00:00 <container>   # 截止某时间
docker logs -t <container>             # 带时间戳
```

### 4.4 资源使用

```bash
docker stats                  # 实时
docker stats --no-stream       # 快照
docker stats --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}'

# 单个容器详细信息
docker inspect <container> | jq '.State, .HostConfig.Memory, .HostConfig.CpuShares'
```

### 4.5 进程 / 文件 / 网络（容器内）

```bash
# 进程
docker top <container>

# 文件改动（对比 image 的 overlay）
docker diff <container>

# 端口映射
docker port <container>

# 文件拷贝
docker cp <container>:/path/in/container ./local/path
docker cp ./local/file <container>:/path/in/container
```

### 4.6 提交 / 导入变更

```bash
# 把运行中容器的变更打包成新镜像（不推荐做生产镜像）
docker commit <container> myimage:custom

# 导出容器文件系统（不是镜像，没有 layer 元信息）
docker export <container> -o container.tar
```

---

## 5. 网络

### 5.1 端口映射

```bash
# -p 语法：-p <host_ip>:<host_port>:<container_port>/<protocol>
docker run -p 8080:80 nginx               # 主机 8080 → 容器 80
docker run -p 127.0.0.1:8080:80 nginx      # 只绑 loopback（更安全）
docker run -p 8080:80/tcp nginx            # 显式协议
docker run -p 8080-8090:8000-8010 nginx    # 端口段
docker run -P nginx                        # 全部 EXPOSE 端口随机映射到主机
```

### 5.2 自定义网络（推荐）

```bash
# 创建
docker network create mynet
docker network create --driver bridge --subnet 172.20.0.0/16 mynet

# 列出
docker network ls
docker network inspect mynet

# 容器加入（推荐用 compose，或 --network）
docker run -d --name web --network mynet nginx
docker network connect mynet <existing_container>
docker network disconnect mynet <container>

# 删除
docker network rm mynet
docker network prune   # 清未用

# 容器间通信：同网络下直接用容器名或别名
docker run -d --name db --network mynet mysql
docker run -d --name app --network mynet -e DB_HOST=db myapp
# app 容器里直接 mysql -h db ... 即可
```

### 5.3 网络模式

| 模式 | 用途 | 写法 |
|------|------|------|
| bridge | 默认，单机隔离 | `--network bridge` |
| host | 共享主机网络栈（最大性能，端口冲突风险） | `--network host` |
| none | 无网络 | `--network none` |
| container:NAME | 共享另一个容器的网络 | `--network container:web` |
| 自定义 bridge | 多容器互通，推荐 | `--network mynet` |

### 5.4 DNS

```bash
# 容器内 DNS 由 dockerd 控制（默认从主机继承）
docker run --dns 8.8.8.8 --dns 114.114.114.114 myapp

# 容器 hostname
docker run --hostname myapp.local myapp
docker exec <container> cat /etc/hosts
docker exec <container> cat /etc/resolv.conf
```

---

## 6. 数据持久化（卷 / 挂载）

### 6.1 三种挂载方式

```bash
# 1) Volume（推荐，docker 管理）
docker volume create mydata
docker run -v mydata:/data myapp
docker run -v mydata:/data:ro myapp         # 只读

# 2) Bind mount（直接挂主机目录，调试/配置常用）
docker run -v /host/path:/container/path:ro myapp
docker run --mount type=bind,source=/host/path,target=/container/path,readonly myapp

# 3) tmpfs（内存盘，存临时数据）
docker run --tmpfs /tmp myapp
docker run --mount type=tmpfs,destination=/tmp,tmpfs-size=100m myapp
```

### 6.2 卷管理

```bash
docker volume ls
docker volume inspect mydata
docker volume rm mydata
docker volume prune            # 清未用
```

### 6.3 备份/恢复

```bash
# 备份（其它容器挂载到目标卷，打包）
docker run --rm \
  -v mydata:/source:ro \
  -v $(pwd):/backup \
  alpine tar czf /backup/mydata-$(date +%Y%m%d).tar.gz -C /source .

# 恢复
docker run --rm \
  -v mydata:/target \
  -v $(pwd):/backup \
  alpine tar xzf /backup/mydata-20260610.tar.gz -C /target

# 直接备份 mysql 卷
docker exec <mysql_container> sh -c 'exec mysqldump --all-databases -uroot -p"$MYSQL_ROOT_PASSWORD"' > backup.sql
```

### 6.4 权限

```bash
# 容器内进程以 root 跑（默认），文件会成 root:root
# 想跟主机用户对齐：
docker run -u $(id -u):$(id -g) -v /data:/data myapp

# 临时改文件 owner
docker run --user 0:0 myapp chown -R 1000:1000 /data

# 推荐镜像里建专用非 root 用户（USER 1000）
```

---

## 7. Compose（v2 语法）

### 7.1 基础 compose 文件

```yaml
# compose.yaml（旧名 docker-compose.yml 也认）
services:
  web:
    image: nginx:alpine
    container_name: nginx
    restart: unless-stopped
    ports:
      - "8080:80"
    volumes:
      - ./conf:/etc/nginx/conf.d:ro
      - nginx_data:/var/log/nginx
    networks:
      - appnet
    environment:
      - TZ=Asia/Shanghai
    depends_on:
      - db
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost/"]
      interval: 30s
      timeout: 5s
      retries: 3

  db:
    image: mysql:8.0
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: *** # 生产别写这，用 .env 文件
    volumes:
      - db_data:/var/lib/mysql
    networks:
      - appnet

volumes:
  db_data:
  nginx_data:

networks:
  appnet:
    driver: bridge
```

`.env` 文件（放项目根目录，跟 compose.yaml 同级）:
```bash
MYSQL_ROOT_PASSWORD=actual-secret-here
```

### 7.2 compose 命令

```bash
# 启动
docker compose up -d                     # 后台
docker compose up -d --build            # 重新构建
docker compose up -d --force-recreate   # 强制重建容器

# 查看
docker compose ps
docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Ports}}'
docker compose logs -f web
docker compose logs --tail 100 web
docker compose top

# 启停
docker compose stop
docker compose start
docker compose restart web
docker compose pause
docker compose unpause

# 缩放（只对未指定 container_name 的服务有效）
docker compose up -d --scale worker=3

# 进容器
docker compose exec web bash
docker compose exec -u root db bash

# 在 compose 网络里跑一次性命令
docker compose run --rm web python manage.py migrate

# 删除
docker compose down              # 删容器、网络
docker compose down -v           # 顺便删卷（危险，删数据）
docker compose down --rmi all    # 顺便删镜像

# 配置校验
docker compose config            # 打印合并后的最终配置
docker compose config -q         # 静默校验（CI 友好）

# 拉镜像
docker compose pull
```

### 7.3 多环境 / 多 compose 文件

```bash
# 基础 compose.yaml + override
docker compose -f compose.yaml -f compose.prod.yaml up -d

# 环境变量
DATABASE_URL=postgres://... docker compose up -d
# 或用 .env.${ENV} 配合：
docker compose --env-file .env.prod up -d
```

### 7.4 compose 部署常用套路

```bash
# 部署脚本模板（幂等）
#!/bin/bash
set -e
APP=/opt/myapp
cd $APP
git pull
docker compose pull
docker compose up -d --remove-orphans
docker image prune -f    # 清悬空镜像
docker system prune -f   # 清所有未用（慎重）
```

---

## 8. 环境变量 / 配置文件注入

```bash
# 单个环境变量
docker run -e KEY=value myapp
docker run -e KEY1=v1 -e KEY2=v2 myapp

# 从文件读
docker run --env-file .env myapp

# 只读配置文件（bind mount）
docker run -v ./my.cnf:/etc/mysql/my.cnf:ro mysql:8.0

# secrets（swarm 模式，或 K8s）
docker secret create db_password ./pw.txt
docker service create --secret db_password myapp
```

---

## 9. 资源限制

```bash
# 内存
docker run -m 512m myapp                    # 硬限 512M
docker run --memory-reservation 256m myapp  # 软限（保证 256M，可短暂超）
docker run --memory-swap 1g myapp           # 内存+swap 总和
docker run --oom-kill-disable myapp         # OOM 时不杀（危险）

# CPU
docker run --cpus 1.5 myapp                 # 最多 1.5 核
docker run --cpuset-cpus 0,1 myapp          # 绑核
docker run --cpu-shares 512 myapp           # 权重（默认 1024）

# 磁盘 IO
docker run --device-read-bps /dev/sda:10mb myapp
docker run --device-write-iops /dev/sda:1000 myapp

# ulimit
docker run --ulimit nofile=65536:65536 myapp
```

容器运行时改：
```bash
docker update -m 1g <container>
docker update --cpus 2 <container>
```

---

## 10. 健康检查

```bash
# Dockerfile 里
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost/ || exit 1
```

```bash
# 运行时
docker inspect --format='{{json .State.Health}}' <container> | jq .

# compose 里
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U postgres || exit 1"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

---

## 11. 日志管理

### 11.1 默认 json-file 驱动

```bash
# 配置（写在 daemon.json）
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",   # 单文件最大
    "max-file": "5"        # 保留几个
  }
}

# 单容器覆盖
docker run --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 myapp
```

### 11.2 其它驱动

```bash
# 推到 syslog
docker run --log-driver=syslog --log-opt syslog-address=tcp://logserver:514 myapp

# 推到 journald
docker run --log-driver=journald myapp
sudo journalctl -u docker CONTAINER_NAME=web

# 无日志（不推荐）
docker run --log-driver=none myapp
```

### 11.3 排错现场

```bash
# 实时跟踪
docker logs -f <container> 2>&1 | grep -i error

# 找时间段的日志（json-file 驱动）
docker inspect <container> | jq -r '.[0].LogPath'
sudo tail -f /var/lib/docker/containers/<id>/<id>-json.log
```

---

## 12. 排障大全

### 12.1 容器起不来

```bash
# 1) 看日志
docker logs <container>
docker logs --tail 200 <container>

# 2) 看退出码
docker inspect <container> | jq '.[0].State'

# 3) 已退出容器进 shell（加 --rm 的进不去）
docker run -it --rm <image> bash   # 用同镜像开个新的查问题

# 4) 覆盖入口
docker run -it --entrypoint bash <image>

# 5) 资源耗尽
docker stats <container>
dmesg | grep -i oom   # OOM 杀进程记录
```

### 12.2 dockerd 起不来

```bash
# 看完整错误
sudo journalctl -u docker -n 100 --no-pager

# 常见 3 个：
# 1) iptables/nftables 冲突 → sudo update-alternatives --set iptables /usr/sbin/iptables-legacy
# 2) 存储驱动坏了 → /var/lib/docker/ 内容不一致，需 docker system prune -a（数据丢）
# 3) daemon.json JSON 错 → python3 -m json.tool /etc/docker/daemon.json
```

### 12.3 镜像拉不下来

```bash
# 1) 先确认不是网络问题
curl -I https://mirror.ccs.tencentyun.com/v2/

# 2) 配 mirror（见 §1.2）

# 3) 手动走 mirror
docker pull mirror.ccs.tencentyun.com/library/mysql:8.0

# 4) 看 dockerd 拉镜像的日志
sudo journalctl -u docker -f | grep -i pull
```

### 12.4 网络问题

```bash
# 容器之间不通
docker network inspect mynet      # 是不是在同一 net
docker exec web ping -c 2 db      # 容器内互测
docker exec web nslookup db       # DNS 解析
docker exec web cat /etc/resolv.conf

# 主机访问不了容器端口
docker port <container>                              # 看实际映射
ss -tlnp | grep <port>                               # 主机监听了吗
sudo iptables -L -n | grep <port>                    # 防火墙
sudo ufw status                                      # UFW

# 容器访问不了外网
docker run --rm alpine ping -c 2 8.8.8.8             # ICMP
docker run --rm alpine wget -qO- ifconfig.me         # HTTPS
```

### 12.5 磁盘满

```bash
# 看 docker 占用
docker system df
docker system df -v

# 清
docker container prune       # 停的容器
docker image prune -a        # 未用镜像
docker volume prune          # 未用卷（小心）
docker network prune         # 未用网络
docker system prune          # 上面全清（会问 y）
docker system prune -a --volumes  # 含卷（非常危险）

# /var/lib/docker/overlay2 单独占满：dific 找最大层
du -sh /var/lib/docker/*
du -sh /var/lib/docker/overlay2/* | sort -h | tail -20
```

### 12.6 容器时区不对

```bash
# 方法 1：挂主机时区
docker run -v /etc/localtime:/etc/localtime:ro myapp
docker run -e TZ=Asia/Shanghai myapp

# 方法 2：compose
environment:
  - TZ=Asia/Shanghai
volumes:
  - /etc/localtime:/etc/localtime:ro
```

### 12.7 容器中文乱码

```bash
environment:
  - LANG=C.UTF-8
  - LC_ALL=C.UTF-8
```

---

## 13. 安全

### 13.1 镜像安全

```bash
# 扫漏洞
docker scan <image>            # 内置（要登录 Docker Hub）
trivy image <image>            # 推荐：trivy

# 只用官方/可信镜像，禁 latest 标签（生产）
# 镜像签名（cosign 之类）— 高级用法
```

### 13.2 容器权限最小化

```bash
# 禁特权
docker run --security-opt no-new-privileges myapp

# 禁所有 capabilities
docker run --cap-drop=ALL myapp

# 只给需要的
docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE myapp

# 禁 root（镜像内 USER 1000 也要有）
docker run --user 1000:1000 myapp

# 只读 rootfs
docker run --read-only myapp

# 禁 network namespace 操作
docker run --security-opt seccomp=default.json myapp  # 默认就开了
docker run --security-opt apparmor=docker-default myapp  # 默认就开了
```

### 13.3 密钥管理

```bash
# 绝不要把 .env 写进镜像
# 绝不要 docker run -e KEY=xxx 还录屏/截图
# 优先用 secrets 机制或挂载的密钥文件
docker run -v /run/secrets:/run/secrets:ro myapp
```

---

## 14. Swarm（多机编排）

本机当前是单机模式，Swarm 关。简单命令备忘：

```bash
# 初始化集群
docker swarm init
docker swarm init --advertise-addr 1.2.3.4

# 看节点
docker node ls

# 起服务
docker service create --replicas 3 --name web -p 80:80 nginx
docker service ls
docker service ps web
docker service scale web=5
docker service update --image nginx:1.27 web
docker service rm web

# 离开集群
docker swarm leave --force
```

> 单机直接用 compose 就行，Swarm 是为多机/多副本设计的。

---

## 15. 监控 / 清理

```bash
# 总体磁盘
docker system df

# 实时
docker stats

# 事件流
docker events --since 10m

# 清理
docker system prune              # 停的容器+未用网络+悬空镜像+build cache
docker system prune -a           # 加上未用镜像
docker system prune -a --volumes # 加上未用卷（数据丢）
docker builder prune             # 只清 build cache
```

生产 cron 清理：
```bash
# /etc/cron.d/docker-cleanup
0 3 * * 0 root docker image prune -a -f --filter "until=168h"  # 7 天前未用镜像
0 3 * * 0 root docker container prune -f                       # 已停止容器
0 3 * * 0 root docker volume prune -f                          # 未用卷
0 3 * * 0 root docker builder prune -f --keep-storage 10GB     # build cache 限 10G
```

---

## 16. 进阶 / 杂项

### 16.1 buildx（多架构构建）

```bash
docker buildx create --use --name mybuilder
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:1.0 --push .
```

### 16.2 私有 registry

```bash
# 登录
docker login registry.cn-hangzhou.aliyuncs.com -u xxx -p yyy
cat ~/.docker/config.json    # 凭据存在这

# 登出
docker logout registry.cn-hangzhou.aliyuncs.com

# 拉私有镜像
docker pull registry.cn-hangzhou.aliyuncs.com/namespace/repo:tag
```

### 16.3 容器内 docker（dind，CI 用）

```bash
docker run --privileged -d --name dind docker:dind
# 主机端口 2375/2376 暴露出来，CI 客户端连进去
```

> 慎用 `--privileged`，只给 CI/构建用。

### 16.4 容器与主机文件互拷

```bash
docker cp ./local.conf <container>:/etc/nginx/conf.d/
docker cp <container>:/var/log/nginx/access.log ./
```

### 16.5 限制用户 / 命名空间

```bash
docker run --userns=host myapp                  # 共享主机用户 ns（少见）
docker run --pid=host myapp                     # 共享主机 PID（看主机进程）
docker run --ipc=host myapp                     # 共享 IPC
```

### 16.6 BuildKit 缓存挂载

```dockerfile
# syntax=docker/dockerfile:1.7
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

---

## 17. 常用诊断一键脚本

```bash
# 收集完整诊断信息（出问题时跑一下）
cat << 'EOF' > /tmp/docker-diag.sh
#!/bin/bash
echo "=== OS ==="
cat /etc/os-release | head -5
echo "=== Kernel ==="
uname -a
echo "=== Docker ==="
docker version --format '{{.Server.Version}} | {{.Client.Version}}'
docker info 2>&1 | grep -E "Driver|Cgroup|Storage|Docker Root Dir|Registry Mirrors" -A 1 | head -20
echo "=== Disk ==="
df -h /var/lib/docker
du -sh /var/lib/docker 2>/dev/null
echo "=== Containers ==="
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
echo "=== Recent dockerd logs ==="
journalctl -u docker -n 30 --no-pager | tail -30
echo "=== Network ==="
docker network ls
echo "=== Volumes ==="
docker volume ls
EOF
chmod +x /tmp/docker-diag.sh
```

---

## 18. 参考

- 官方文档：https://docs.docker.com/
- Compose 规范：https://docs.docker.com/compose/compose-file/
- 排错 wiki：https://docs.docker.com/engine/Troubleshooting/
- 本机现有应用参考：`/root/hermes_from_43/hermes-agent/docker-compose.yml`
- 上次踩坑：daemon.json JSON 闭合 + systemd 限流重置

---

## 修订记录

| 日期 | 修订内容 |
|------|----------|
| 2026-06-10 | 初版，基于本机（Ubuntu24.04/Docker26.1.4）环境编写 |
