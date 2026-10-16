# Mini IM - 全栈极简分布式即时通讯系统 (MVP)

基于现代高并发架构设计的最小可用 IM 系统，完整支持登录注册、个人信息管理（MinIO头像上传）、好友与群组全生命周期管理、实时消息（文本与媒体附件）收发。

---

## 🏗️ 整体架构设计 (Tech Stack & Architecture)

```
                     ┌────────────────────────────────────────┐
                     │   React + shadcn/ui + Tailwind Frontend │
                     │   (Vite + TypeScript + Lucide Icons)   │
                     └───────────────┬──────────────────▲─────┘
                                     │                  │
                        HTTP REST    │                  │ WebSocket (WSS/WS)
                      (Auth/Upload/  │                  │ Real-time Events
                       Friend/Group) │                  │
                                     ▼                  │
                     ┌──────────────────────────────────┴─────┐
                     │          Flask API & WS Gateway         │
                     │  - Flask-Sock (WebSocket Handler)       │
                     │  - JWT Auth & REST Endpoints            │
                     │  - Kafka Producer (Chat Pipeline)       │
                     │  - MinIO S3 SDK (Media Upload)          │
                     └───────────────┬──────────────────▲─────┘
                                     │                  │
                Publish Message      │                  │ Redis Pub/Sub
                to Kafka Topic       ▼                  │ Broadcast to Sockets
                ───────────────> ┌────────┐        ┌────┴────┐
                                 │ Kafka  │        │  Redis  │ (Presence & Status)
                                 └────┬───┘        └─────────┘
                                      │
                                      ▼
                               ┌──────────────┐
                               │ Kafka Worker │ (Background Consumer)
                               └──────┬───────┘
                                      │ Persist
                                      ▼
                               ┌──────────────┐    ┌──────────────┐
                               │  PostgreSQL  │    │    MinIO     │
                               │  (Database)  │    │  (S3 Media)  │
                               └──────────────┘    └──────────────┘
```

### 技术栈选型
- **后端服务**: Python 3.9+, Flask, Flask-Sock (标准 WebSocket WSS/WS), PyJWT, psycopg2
- **持久化存储**: PostgreSQL 15+ (用户、好友关系、群组、群成员、消息记录与索引)
- **高速缓存与状态**: Redis 7+ (用户在线状态维护、离线检测、跨节点 Pub/Sub 广播)
- **消息队列**: Apache Kafka 3.7+ (高吞吐消息摄取管道、异步落库解耦、防并发雪崩)
- **对象存储**: MinIO S3 (用户头像、聊天图片、聊天文件附件存储与公开分发)
- **前端界面**: React 18/19, TypeScript, Vite, Tailwind CSS, Radix UI (shadcn 规范), Lucide React

---

## 🚀 核心 MVP 功能列表

1. **登录与注册**:
   - 用户名密码注册与登录，PBKDF2 安全哈希加盐加密。
   - JWT Access Token 签名与无状态鉴权。
   - 提供 4 个预置演示账号一键登入 (`alice`, `bob`, `charlie`, `diana`，密码 `123456`)。

2. **个人信息修改**:
   - 支持上传本地头像图片至 **MinIO** 对象存储并实时更新。
   - 修改昵称、个性签名 (Bio)。
   - 切换在线状态 (在线 🟢、忙碌 🔴、离开 🟡)，并通过 Redis 全局广播通知好友。

3. **好友与通讯录管理**:
   - 全局搜索用户（按用户名或昵称模糊匹配）。
   - 发送好友申请，附带验证说明。
   - 查看收到的申请与发出的申请，一键“同意”或“拒绝”；同意后自动建立双向好友记录。
   - 查看好友列表（按在线/离线分组展示），支持解除好友关系。

4. **群组管理**:
   - 创建新群聊：设置群名称、群简介、上传群头像到 MinIO。
   - 搜索群聊大厅与一键加入。
   - 查看群成员列表、成员在线状态、成员角色（群主、管理员、普通成员）。
   - 邀请好友批量入群。
   - 退出群聊、群主解散群聊。

5. **消息收发 (文本 & 媒体)**:
   - **双工实时**: 支持基于 WebSocket (WSS/WS) 毫秒级双向收发，支持断线自动重连与心跳探测。
   - **消息类型**:
     - **文本消息**: 支持表情快捷面板 (Emoji Picker)、换行与链接渲染。
     - **图片消息**: 点击上传到 MinIO，自动发送图片卡片，支持全屏灯箱缩放预览与原图下载。
     - **文件附件**: 支持任意类型文件上传至 MinIO，提供文件名、文件体积与一键下载。
   - **全链路削峰持久化**: 消息发出 -> Kafka Topic 摄取 -> 消费者线程批量写入 PostgreSQL -> Redis 消息发布 -> WebSocket 推送给接收方。

---

## 🛠️ 快速启动指南

### 1. 启动基础设施中间件 (PostgreSQL, Redis, Kafka, MinIO)

如果使用 Docker，可以在 `mini-im` 根目录下执行：
```bash
docker compose up -d
```

默认端口与服务分配：
- PostgreSQL: `127.0.0.1:5433` (用户: `postgres`, 密码: `postgrespassword`, 数据库: `mini_im_db`)
- Redis: `127.0.0.1:6379`
- Kafka: `127.0.0.1:9092`
- MinIO: `127.0.0.1:9000` (控制台: `9001`, 用户: `minioadmin`, 密码: `minioadminpassword`)

### 2. 启动后端服务 (Backend)

```bash
cd mini-im/backend
# 激活虚拟环境
source venv/bin/activate
# 初始化预设演示数据
python seed_data.py
# 启动 Flask API 与 WebSocket 服务
python app.py
```
后端将在 `http://127.0.0.1:5001` 启动。

### 3. 启动前端界面 (Frontend)

```bash
cd mini-im/frontend
# 启动 Vite 开发服务
npm run dev
```
打开浏览器访问: `http://localhost:5173`

---

## 🧪 自动化全链路回归测试

我们在 `mini-im/test_full_suite.py` 编写了涵盖全部 10 项核心 MVP 功能的端到端自动化测试脚本：

```bash
cd mini-im
./backend/venv/bin/python test_full_suite.py
```

测试执行项覆盖：
1. PostgreSQL / Redis / Kafka / MinIO 健康检查
2. 动态注册双测试账号
3. MinIO 上传头像与修改个人资料
4. 用户搜索、发送好友申请、接受好友申请
5. WebSocket 实时接入与双向鉴权
6. Kafka 管道直发文本消息与 WebSocket 实时推送
7. MinIO 媒体图片上传与媒体消息推送
8. 群组创建、好友邀请、群成员列表查询与群消息广播
9. 消息历史记录分页与未读会话汇总
10. 群聊退出、群聊解散与好友删除

测试输出全部通过：
```
============================================================
SUCCESS: 10/10 TEST SUITES PASSED! ALL MVP CRITERIA VERIFIED!
============================================================
```
