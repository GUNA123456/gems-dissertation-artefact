# 🛍️ StyleHub Microservices Architecture

A lightweight, high-performance **Microservices E-Commerce Application** built with **Python**, **FastAPI**, **Uvicorn**, **Redis**, **Docker**, and **Kubernetes (Helm)**. Inspired by cloud-native microservice benchmark architectures.

---

## 🏗️ Microservices Topology

StyleHub is composed of **10 decoupled microservices** communicating over clean, asynchronous REST APIs:

```
                          ┌───────────────────────┐
                          │   Frontend Gateway    │ (Port 8080)
                          └───────────┬───────────┘
                                      │
     ┌──────────────────┬─────────────┼──────────────┬──────────────────┐
     ▼                  ▼             ▼              ▼                  ▼
┌──────────┐      ┌──────────┐  ┌──────────┐   ┌──────────┐      ┌──────────────┐
│ Product  │      │   Cart   │  │ Currency │   │    Ad    │      │ Checkout     │
│ Catalog  │      │ Service  │  │ Service  │   │ Service  │      │ Orchestrator │
│ (8081)   │      │  (8082)  │  │  (8083)  │   │  (8087)  │      │   (8086)     │
└──────────┘      └────┬─────┘  └──────────┘   └──────────┘      └──────┬───────┘
                       │                                                │
                 ┌─────▼────┐                 ┌─────────────┬───────────┼───────────┐
                 │  Redis   │                 ▼             ▼           ▼           ▼
                 │ Cache    │           ┌──────────┐  ┌──────────┐ ┌──────────┐ ┌──────────┐
                 │  (6379)  │           │   Recs   │  │ Shipping │ │ Payment  │ │  Email   │
                 └──────────┘           │  (8084)  │  │  (8085)  │ │  (8089)  │ │  (8088)  │
                                        └──────────┘  └──────────┘ └──────────┘ └──────────┘
```

### 📋 Service Catalog

| Service Name | Port | Description |
| :--- | :--- | :--- |
| **Frontend Gateway** | `8080` | Web Storefront UI handling user search, cart views, and checkout forms. |
| **Product Catalog Service** | `8081` | Manages apparel catalog data, SKU lookups, and keyword search. |
| **Cart Service** | `8082` | Manages user shopping carts backed by Redis with in-memory fallback. |
| **Currency Service** | `8083` | Handles multi-currency conversions relative to USD. |
| **Recommendation Service** | `8084` | Generates tailored product recommendations ("You May Also Like"). |
| **Shipping Service** | `8085` | Calculates dynamic shipping quotes and carrier tracking IDs. |
| **Checkout Orchestrator** | `8086` | Orchestrates payment, shipping, email notification, and cart reset. |
| **Ad Service** | `8087` | Serves context-targeted promotional banners. |
| **Email Service** | `8088` | Dispatches order receipts and shipping confirmation logs. |
| **Payment Service** | `8089` | Validates credit card formats and generates transaction records. |

---

## ⚡ Quickstart & Local Execution

### 1. Native Python Launcher (No Container Needed)
To run all microservices locally in a virtual environment:

```bash
chmod +x run_local.sh
./run_local.sh
```
Then open **[http://localhost:8080](http://localhost:8080)** in your browser.

### 2. Docker Compose Execution
To build and launch all 10 microservices plus Redis in isolated containers:

```bash
docker-compose up --build
```

### 3. Kubernetes / Helm Deployment
To deploy to a Kubernetes cluster (Minikube / Kind / GKE):

```bash
helm install stylehub ./stylehub-helm
```

---

## 🛠️ Technology Stack & Design Decisions

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) - High-performance Python web framework with native Pydantic validation.
- **ASGI Web Server**: [Uvicorn](https://www.uvicorn.org/) - Asynchronous Server Gateway Interface engine powering all services.
- **State Management**: [Redis](https://redis.io/) - Fast key-value store for user cart persistence.
- **Data Schemas**: `src/common/models.py` - Centralized Pydantic schemas enforcing input validation across endpoints.

---

## 📜 License & Acknowledgments

Built for microservice reliability research and demonstration purposes.
