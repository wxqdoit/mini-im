# Mini IM - 100K 并发生产级分布式架构改造与容器化部署手册

Mini IM 是一个高并发、生产级分布式即时通讯（IM）系统。本项目已全面完成架构重构与全容器化编排，支持 **100,000 人同时在线（100K Concurrent Connections）**、**5,000+ TPS 峰值消息吞吐**、**毫秒级下发**与**零消息丢失**的高可用架构。

---

## 🏗️ 整体分布式微服务拓扑

```
                             ┌──────────────────────────┐
                             │    L4 SLB / Cloud NLB    │
                             └────────────┬─────────────┘
                                          │
                         ┌────────────────┴────────────────┐
                         ▼                                 ▼
             ┌───────────────────────┐         ┌───────────────────────┐
             │      Nginx 网关       │         │      Nginx 网关       │
             │   (Reverse Proxy)     │         │ (Consistent Token Hash│
             └───────────┬───────────┘         └───────────┬───────────┘
                         │                                 │
                         ▼                                 ▼
             ┌───────────────────────┐         ┌───────────────────────┐
             │  REST API 集群 (多实例) │         │ WS 网关集群 (多实例)  │
             │  (业务/用户/群组/文件)  │         │ (维护长连接与精准下发) │
             └───────────┬───────────┘         └───────────┬───────────┘
                         │                                 │
                         │          ┌──────────────────────┤
                         ▼          ▼                      ▼
                 ┌──────────────┐┌──────────────┐    ┌──────────────┐
                 │  Kafka 集群  ││ Redis 集群   │<───┤ 分布式路由表 │
                 │ (多分区削峰) ││(Session Router│   │(Session Map) │
                 └──────┬───────┘└──────────────┘    └──────────────┘
                        │
                        ▼
                 ┌──────────────┐
                 │ Kafka Worker │ (多实例微批聚合落库)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │  PgBouncer   │ (连接池事务复用中间件)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │  PostgreSQL  │ (按月声明式时间范围分区表)
                 └──────────────┘
```

---

## 🚀 核心改造技术亮点

### 1. 前后端全栈 Docker 化（Zero-Dependency Docker Launch）
- **前端多阶段构建**：`frontend/Dockerfile` 使用 `node:20-alpine` 编译 React + Vite + TypeScript 前端，再打包进轻量 `nginx:alpine`，宿主机无需安装 Node.js 或构建工具。
- **后端微服务角色分工**：`backend/Dockerfile` 构建统一镜像，通过 `SERVICE_ROLE` 区分 `api`、`gateway`、`worker`，按需水平扩缩容。
- **Nginx L7 反向代理与负载均衡**：`nginx.conf` 统一代理入口（端口 80/443）：
  - `/` -> 前端 React SPA 静态服务（Gzip 压缩，SPA 路由回退）
  - `/api/` -> 后端 REST API 集群
  - `/ws` -> WebSocket 网关集群（基于 token 参数的 Consistent Hash 保证同一用户会话亲和性）
  - `/mini-im-media/` -> MinIO 对象存储安全静态资源代理

### 2. 精准会话路由 (Precision Session Router)
- **根除广播风暴**：彻底废除了传统 IM 在多网关间全量广播的缺陷。
- **节点专用通道**：每个网关节点分配全局唯一 `NODE_ID`，仅订阅私有频道 `mini_im:node:{NODE_ID}`。
- **$O(1)$ 批量路由**：群聊消息在消费端经由 Redis Pipeline 一次性获取所有在线成员所属网关，按网关聚合后单次推送，Pub/Sub 广播流量降低 90% 以上。

### 3. 时序可靠性与离线增量补齐 (SeqID + ACK + Delta Sync)
- **严格单调自增 SeqID**：每个会话在 Redis 维护 64 位自增序号，保障分布式时序绝对单调递增。
- **可靠回执 (Client ACK)**：客户端在收到推送后发送 `{type: "ack", msg_id: ..., seq_id: ...}`，保障链路送达。
- **离线增量同步 (Sync 协议)**：客户端弱网重连仅凭本地最大 `last_seq_id`，调用 `/api/messages/sync` 或 WebSocket `{type: "sync"}` 增量拉取缺失包。

### 4. Kafka Micro-Batch 批量落库
- **微批持久化**：后台消费者累积满 200 条消息或间隔达到 50ms 触发批量入库。
- **execute_values 单事务多行写入**：相比传统单条插入，数据库 IOPS 与事务等待下降 90% 以上。

### 5. PostgreSQL 原生时间范围声明式分区 (Declarative Partitioning)
- `messages` 表全面重构为 `PARTITION BY RANGE (created_at)`。
- 按月创建分区（如 `messages_2026_10`、`messages_2026_11`）与 `messages_default` 兜底分区。
- 历史数据查询直接下推分区裁剪（Partition Pruning），彻底解决单表千万级扫描性能劣化。

---

## 🛠️ 生产环境一键容器化集群部署 (Docker Compose)

### 1. 一键启动所有服务
```bash
# 启动所有服务（Postgres, PgBouncer, Redis, Kafka, MinIO, Frontend, API, WS Gateways, Kafka Worker, Nginx LB）
docker compose up -d --build
```

### 2. 初始化演示账号与群组（可选）
```bash
# 在 API 容器中执行种子数据生成（自动创建 alice, bob, charlie, diana，初始密码均为 123456）
docker exec mini_im_api_1 python seed_data.py
```

### 3. 访问应用
- **Web 前端页面**：浏览器直接打开 `http://localhost` 或 `http://localhost:80`（也可直接访问 `http://localhost:5173`）
- **API 健康检查**：`http://localhost/api/health`
- **MinIO 控制台**：`http://localhost:9001`（账号 `minioadmin`，密码 `minioadminpassword`）

### 4. 容器集群服务清单
| 服务名称 | 容器名称 | 内部端口 | 暴露端口 | 职责描述 |
| :--- | :--- | :--- | :--- | :--- |
| `frontend` | `mini_im_frontend` | 80 | 5173 | React + Vite 生产编译 SPA 容器 |
| `api_server` | `mini_im_api_1` | 5001 | 5001 | REST API 服务（认证、好友、群组、加密公钥交换） |
| `ws_gateway_1` | `mini_im_ws_gw_1` | 5002 | 5002 | WebSocket 长连接网关节点 1（维护 15,000+ 连接） |
| `ws_gateway_2` | `mini_im_ws_gw_2` | 5003 | 5003 | WebSocket 长连接网关节点 2（维护 15,000+ 连接） |
| `kafka_worker` | `mini_im_kafka_worker` | - | - | Kafka 后台多分区批量落库与精准路由派发服务 |
| `nginx_lb` | `mini_im_nginx_lb` | 80, 443 | 80, 443 | L7 统一反向代理、路由分流与会话一致性哈希负载均衡器 |
| `postgres` | `mini_im_postgres` | 5432 | 5433 | 核心关系型数据库（按月范围分区表） |
| `pgbouncer` | `mini_im_pgbouncer` | 6432 | 6432 | 数据库连接池中间件（支持 10,000+ 客户端连接复用） |
| `redis` | `mini_im_redis` | 6379 | 6379 | 用户路由表、在线状态、SeqID 发号器与 Pub/Sub 交换机 |
| `kafka` | `mini_im_kafka` | 29092 | 9092 | KRaft 架构高吞吐消息队列（多分区削峰填谷） |
| `minio` | `mini_im_minio` | 9000, 9001 | 9000, 9001 | S3 兼容分布式对象存储（存储头像与聊天媒体） |

---

## 🧪 自动化测试与基准压测套件

### 1. 混沌容灾与节点 Crash 漂移测试
```bash
./backend/venv/bin/python test_failover_chaos.py
```
*验证：Gateway 1 突发 Crash，客户端秒级自动重连 Gateway 2，Redis 会话路由自动无感漂移，双向消息零丢失。*

### 2. 100K 架构核心协议自动化测试
```bash
./backend/venv/bin/python test_production_100k.py
```
*验证：精准路由映射、严格单调自增 SeqID、客户端 ACK 回执与离线增量 Sync 同步。*

### 3. 高吞吐写入基准测试 (TPS Benchmark)
```bash
./backend/venv/bin/python benchmarks/benchmark_tps.py
```
*验证：多用户并发请求、Kafka 削峰排队、数据库微批持久化速率采样。*

### 4. 万级并发 WebSocket 长连接与心跳测试
```bash
PYTHONPATH=backend ./backend/venv/bin/python benchmarks/stress_test_100k.py --connections 1000 --duration 15 --ping-interval 3
```
*验证：大批量 WebSocket 并发握手、持续 Ping/Pong 链路健康、RTT 网络延迟 (P50/P95/P99) 采样统计。*

### 5. 全业务功能回归 (10/10 Suites) & 零知识端到端加密 (E2EE) 测试
```bash
./backend/venv/bin/python test_full_suite.py
./backend/venv/bin/python test_e2ee_flow.py
```

---

## ⚙️ Linux 生产操作系统内核参数建议 (`/etc/sysctl.conf`)

在承载 100,000 并发长连接的 Linux 主机上执行：

```bash
# 文件描述符
sysctl -w fs.file-max=2097152

# 最大积压队列
sysctl -w net.core.somaxconn=65535
sysctl -w net.ipv4.tcp_max_syn_backlog=65535

# 端口复用与可用端口范围
sysctl -w net.ipv4.tcp_tw_reuse=1
sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# 连接跟踪表调优
sysctl -w net.netfilter.nf_conntrack_max=1048576
```
