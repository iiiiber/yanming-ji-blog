# Docker 从入门到排查：容器基础、达梦定位与日常运维

> 这篇文章的起因是一次真实的排查：用户问"达梦数据库装在哪"，先在 `docker ps` 里找不到，再在宿主机上也找不到，最后靠"应用连的库在哪"才定位到方向。这篇把 Docker 从概念到实战排查完整记下来，既是一份入门笔记，也是一张排障地图。

---

## 1. 先搞懂三个概念

### 1.1 镜像 vs 容器

**镜像（image）** 像"安装包/模板"，是一份只读的文件系统快照；**容器（container）** 是镜像跑起来的实例，一个镜像可以启动多个容器。

```bash
docker images   # 看本机有哪些镜像（模板）
docker ps       # 看哪些容器在运行（实例）
```

日常操作的对象是容器，容器从镜像启动，但两者要分清楚：删容器不等于删镜像，删了镜像以后还能再 pull 回来。

### 1.2 容器是临时的

容器里装的包、改的配置、写的文件，容器一删就没了。真正要保留的数据（数据库文件、上传文件、日志）必须放到**数据卷（volume）**或挂载宿主机目录，否则删容器等于删数据。

这也是为什么生产环境一般用 docker-compose 而不是裸 `docker run`：compose 文件把端口、挂载、环境变量、重启策略都写清楚，整套配置可复制、可回滚。

### 1.3 端口映射和数据卷

```bash
# -p 8080:80 把容器内 80 端口映射到宿主机 8080
docker run -d --name web -p 8080:80 nginx

# -v 挂载：宿主机目录 /data 对应容器内 /app/data
docker run -d --name app -v /data:/app/data myapp
```

注意：容器内访问不到宿主机端口，访问宿主服务要写宿主机 IP；容器之间靠容器名互相访问。

---

## 2. 日常必会命令

### 2.1 看容器和镜像

```bash
docker ps                # 运行中的容器
docker ps -a             # 所有容器（含已停止的）
docker images            # 本机所有镜像
```

`docker ps -a` 的输出里，`NAMES` 列就是容器名，后面的命令都可以用它代替容器 ID。

### 2.2 启动 / 停止 / 重启

```bash
docker start <容器名>     # 启动已停止的容器
docker stop <容器名>      # 停止
docker restart <容器名>   # 重启
```

### 2.3 进容器

```bash
docker exec -it <容器名> bash   # 常见方式
docker exec -it <容器名> sh     # 精简镜像没有 bash 时用 sh
docker exec -it -u root <容器名> bash   # 指定 root 身份进入
```

要点：

- `exec` 只能进**运行中**的容器，容器没跑先 `docker start`。
- `-i` 保持交互，`-t` 分配终端，两个都要带，否则敲命令没反应。
- 进入后不一定有 root 权限，达梦容器通常还要 `su - dmdba`。

### 2.4 看日志

```bash
docker logs <容器名>              # 最近日志
docker logs -f <容器名>           # 实时跟踪，Ctrl+C 退出
docker logs --tail 100 <容器名>   # 只看最后 100 行
```

容器启动失败、数据库连不上，第一件事就是看日志。

### 2.5 看容器详情（最实用）

```bash
docker inspect <容器名>                                  # 全部信息
docker inspect <容器名> --format '{{json .Config.Env}}'   # 只看环境变量
docker inspect <容器名> --format '{{json .Mounts}}'       # 只看数据卷挂载
docker top <容器名>                                       # 容器内的进程
docker stats                                              # 实时 CPU/内存
```

排查"数据库在哪"时，`Config.Env` 和 `Mounts` 是最有用的两个字段：数据库地址、账号密码、数据目录常常就藏在这里。

### 2.6 删除容器和镜像

```bash
docker rm <容器名>    # 删容器（需先停止）
docker rmi <镜像名>   # 删镜像
```

### 2.7 命令速查表

| 场景 | 命令 | 说明 |
|---|---|---|
| 看运行中的容器 | `docker ps` | 最常用 |
| 看所有容器 | `docker ps -a` | 含已停止 |
| 看镜像 | `docker images` | 本机模板列表 |
| 进容器 | `docker exec -it 名字 bash` | 无 bash 换 sh |
| 看日志 | `docker logs -f 名字` | -f 实时跟踪 |
| 看环境变量 | `docker inspect 名字 --format '{{json .Config.Env}}'` | 找配置首选 |
| 看挂载 | `docker inspect 名字 --format '{{json .Mounts}}'` | 找数据目录 |
| 启动/停止/重启 | `docker start/stop/restart 名字` | 对容器操作 |
| 删容器 | `docker rm 名字` | 先 stop |
| 删镜像 | `docker rmi 镜像名` | 镜像不是容器 |

---

## 3. 进容器后怎么找东西

进去先确认自己在哪、有什么：

```bash
pwd
ls -la
```

然后找配置文件——应用代码一般在 `/app`、`/opt`、`/usr/src/app` 之类的位置：

```bash
# 全盘找配置类文件
find / -maxdepth 4 \( -name "appsettings*.json" -o -name "*.yml" -o -name "*.yaml" -o -name ".env" \) 2>/dev/null

# 找到目录后直接搜数据库连接关键字
grep -rniE "jdbc:dm|dameng|dm8|5236|ConnectionString|DataSource" /app 2>/dev/null
```

数据库连接串通常长这样：`jdbc:dm://IP:5236`，看到 `IP:5236` 就知道数据库在哪台机器。

---

## 4. 排查"数据库到底在哪"的通用思路

不管什么数据库，思路都一样：**应用一定要连数据库，连接信息必然写在配置里**。

```bash
# 第 1 步：看应用容器环境变量
docker inspect <应用容器> --format '{{json .Config.Env}}'

# 第 2 步：进容器翻配置
docker exec -it <应用容器> sh
grep -rniE "jdbc|5236|ConnectionString|DataSource" /app 2>/dev/null

# 第 3 步：宿主机搜配置
grep -rniE "jdbc:dm|dameng|dm8|5236|SYSDBA" /www /opt /root 2>/dev/null | head -30

# 第 4 步：有可疑 IP 就试端口
nc -zv 目标IP 5236
```

如果 IP 是内网地址（172.x、192.168.x、10.x），说明数据库在另一台内网服务器，要去那台机器上查。

---

## 5. 达梦数据库专项排查

达梦（DM8）默认端口 **5236**，默认用户 `SYSDBA`。排查分两层：先看 Docker，再看宿主机。

### 5.1 Docker 里有没有达梦

```bash
# 看运行中的容器（docker ps 只显示运行中的）
docker ps -a | grep -iE "dameng|dm8|dmdb"

# 看有没有达梦镜像
docker images | grep -iE "dameng|dm8"
```

注意：`docker ps` 只看运行中的容器，有镜像但没容器、有容器但停了，都要用 `docker ps -a` 才看得到。

### 5.2 有容器：查配置并进容器用 disql

```bash
# 看端口、环境变量、数据卷
docker inspect <容器名> | grep -iE "5236|Env|Mounts"
docker logs <容器名> 2>&1 | head -50   # 启动日志常带初始账号密码

# 进容器
docker exec -it <容器名> bash

# 找安装目录（常见 /opt/dmdbms 或 /home/dmdba/dmdbms）
find / -name disql 2>/dev/null

# 切到达梦用户并用 disql 连接
su - dmdba
/opt/dmdbms/bin/disql SYSDBA/SYSDBA@localhost:5236
```

连上后的常用查询：

```sql
-- 看版本
SELECT * FROM v$version;

-- 看实例状态
SELECT name, status$ FROM v$instance;

-- 看所有数据库
SELECT name FROM v$database;

-- 看所有用户
SELECT username FROM dba_users;

-- 看某用户下的表
SELECT table_name FROM dba_tables WHERE owner='SYSDBA';
```

`disql` 和 Oracle 的 sqlplus 用法类似，是达梦自带的命令行客户端。

### 5.3 宿主机上查达梦（命令清单）

| 类别 | 命令 | 说明 |
|---|---|---|
| 进程 | `ps -ef \| grep -iE "dmserver\|dmap\|dmwatch"` | 达梦在跑一定有 dmserver |
| 端口 | `ss -tlnp \| grep 5236` | 默认端口 5236 |
| 服务 | `systemctl list-units --all \| grep -i dm` | 看服务有没有注册 |
| 安装目录 | `ls -d /opt/dmdbms /home/dmdba/dmdbms` | 常见安装位置 |
| 命令行工具 | `find / -maxdepth 6 -name disql -o -name dminit` | 有工具 = 装过 |
| 安装包 | `rpm -qa \| grep -iE "dameng\|dm8"` | CentOS 系 |
| 安装包 | `dpkg -l \| grep -iE "dameng\|dm8"` | Ubuntu/Debian 系 |
| 数据文件 | `find / -maxdepth 8 -name dm.ini -o -name dm.ctl` | 实例数据目录 |
| 用户 | `getent passwd \| grep -i dmdba` | 达梦专用用户 |
| 配置关键字 | `grep -rniE "dameng\|dm8\|jdbc:dm\|5236" /etc /opt /www` | 全盘搜配置 |
| 日志 | `ls /var/log/ \| grep -i dm` | 达梦日志目录 |

实际排查时先跑两条，基本必中：

```bash
ss -tlnp | grep 5236
ps -ef | grep -iE "dmserver|dmap|dmwatch"
```

查到进程后，进程命令行一般带安装路径（如 `/opt/dmdbms/bin/dmserver`），顺着就能找到实例和数据目录。

### 5.4 主机和 Docker 都查不到怎么办

说明达梦不在这台机器上，也别慌，按优先级继续：

1. **看应用连接配置**——应用能跑就一定配了数据库地址，这是最可靠的线索。
2. **找部署文档和启动脚本**——docker-compose.yml、k8s yaml、运维文档里通常写了数据库主机。
3. **问部署的人**——一句"达梦在哪台机器"往往比查半天快。
4. **网络探测**——从能访问内网的机器上 `nc -zv 目标IP 5236`，能连上就说明数据库在那。
5. **看应用日志**——数据库连接报错里常带主机名或 IP。

---

## 6. 主机资源排查

### 6.1 内存

```bash
free -h                    # 总量/已用/可用/Swap
ps aux --sort=-%mem | head -15   # 内存占用最高的进程
docker stats               # 每个容器的实时 CPU/内存
```

看内存重点看 `available`（可用）而不是 `free`（空闲），因为缓存可以回收。Swap 使用偏高说明内存有压力。

### 6.2 存储

```bash
df -h                      # 磁盘使用率
df -i                      # inode 使用率（小文件太多会先爆 inode）
du -xsh /www/* /root /var/log 2>/dev/null | sort -rh | head   # 找大目录
```

### 6.3 容器日志撑爆磁盘

容器日志默认全量写在宿主机 `/var/lib/docker/containers/<ID>/*-json.log`，跑久了会撑爆磁盘，而且在容器内查不到：

```bash
docker system df                                   # 镜像/容器/卷/日志占用总览
du -sh /var/lib/docker/containers/*/*-json.log 2>/dev/null | sort -rh | head
docker system prune                                # 清理停止容器和悬空镜像（慎用）
```

---

## 7. 进阶注意事项

### 7.1 用 docker-compose 管理

多容器项目（比如应用 + Redis + 数据库）推荐 compose：一次 `docker compose up -d` 拉起整套，配置全部在文件里。

```yaml
version: "3"
services:
  app:
    image: museum-manager:202611041504
    ports:
      - "5000:5000"
    environment:
      DB_HOST: dm
      DB_PORT: "5236"
    volumes:
      - app-data:/app/data
    restart: always
  redis:
    image: redis:6.0.9
    restart: always
volumes:
  app-data:
```

compose 里容器之间靠**服务名**互访，所以数据库地址写成 `dm:5236` 这种名字而不是 IP，看到别奇怪。

### 7.2 网络要点

- `-p 8080:80` 是端口映射，容器内访问不到宿主机端口。
- 容器之间靠容器名/服务名访问（compose 会自动建内部网络）。
- 查连通性用 `docker exec -it <容器> sh -c 'nc -zv dm 5236'`。

### 7.3 资源限制与自启动

生产容器建议加限制，防止某个容器拖垮整台机器：

```bash
docker run -d --name app --memory 2g --cpus 2 --restart always myapp
```

`--restart always` 让容器挂了自动拉起，机器重启后服务也能恢复。

### 7.4 安全习惯

- 密码不要硬编码进镜像或代码，用环境变量注入。
- 只暴露需要的端口，不要无脑映射。
- 镜像 tag 带日期/版本（如 `202611041504`），不要只用 `latest`。

### 7.5 升级与回滚

用版本化的镜像 tag，升级就是换 tag 重新起容器；出问题可以立即切回旧 tag，而不是在容器里手改配置。

### 7.6 学习路径建议

```text
基础：docker run 常用参数（-d -p -v -e --restart --name）
→ compose：写一个多服务项目
→ Dockerfile：构建自己的镜像
→ 进阶：网络模式（bridge/host）、存储驱动、编排（K8s/Swarm）
```

命令不用背，`docker 命令 --help` 随时查；关键是理解"镜像—容器—数据卷—网络"这四者的关系。

---

## 8. 排查思路总结

一次"找不到数据库"的排查，按这个顺序走：

1. `docker ps -a` 看有没有对应容器，有就 `inspect` + 进容器看配置。
2. 没有容器，就在宿主机查进程、端口、服务、安装目录。
3. 都没有，说明数据库在别的机器——回头查**应用连接配置**，地址一定写在某处。
4. 找到地址后用 `nc -zv IP 5236` 验证连通性。
5. 最终定位后，把数据库主机、账号、端口记进文档，避免下次再查一遍。

> 排查的本质不是"记住所有命令"，而是知道**线索藏在哪里**：数据库在应用配置里，数据在数据卷里，日志在宿主目录里。
