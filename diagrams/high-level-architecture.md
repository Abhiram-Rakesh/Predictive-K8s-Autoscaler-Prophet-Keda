```mermaid
graph TD
    Traffic([External Traffic])

    subgraph EKS ["AWS EKS Cluster (ap-south-1)"]

        subgraph default ["default namespace"]
            LG[Load Generator]
            DA["Demo App\nnginx + prometheus-exporter"]
        end

        subgraph monitoring ["monitoring namespace"]
            PROM["Prometheus\nkube-prometheus-stack"]
            GRAF["Grafana\nDashboards"]
        end

        subgraph keda_ns ["keda namespace"]
            KEDA["KEDA Operator\nScaledObject controller"]
        end

        subgraph scaler_ns ["default namespace (scaler)"]
            PS["Predictive Scaler\nFastAPI :8080\n/desired-replicas"]
        end

    end

    subgraph infra ["AWS Infrastructure"]
        TF["Terraform\nEKS + VPC + NAT GW"]
        GHCR["GHCR\nScaler Image :sha"]
    end

    Traffic -->|HTTP requests| LG
    LG -->|drives load| DA
    DA -->|request rate metrics| PROM
    PROM -->|load history 48h| PS
    PS -->|forecast → replica count| KEDA
    PROM -->|live RPS reactive trigger| KEDA
    KEDA -->|max of predictive + reactive| DA
    PROM --> GRAF
    TF -->|provisions| EKS
    GHCR -->|pulls image| PS

    style PS fill:#1D9E75,color:#fff
    style KEDA fill:#326CE5,color:#fff
    style PROM fill:#E6522C,color:#fff
    style DA fill:#444,color:#fff
    style LG fill:#888,color:#fff
    style GRAF fill:#F46800,color:#fff
    style TF fill:#7B42BC,color:#fff
    style GHCR fill:#333,color:#fff
```
