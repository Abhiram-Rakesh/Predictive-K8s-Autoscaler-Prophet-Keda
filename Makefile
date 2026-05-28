SHELL := /bin/bash
AWS_REGION ?= ap-south-1
CLUSTER ?= predictive-autoscaler
IMAGE ?= ghcr.io/abhiram-rakesh/predictive-scaler:latest

.PHONY: help sim cluster-up kubeconfig addons deploy demo port-forward cluster-down test

help:
	@echo "Targets:"
	@echo "  sim          Run the offline simulation, regenerate the chart (no AWS)"
	@echo "  test         Run unit tests"
	@echo "  cluster-up   terraform apply — provision the EKS cluster"
	@echo "  kubeconfig   Point kubectl at the cluster"
	@echo "  addons       Install metrics-server, kube-prometheus-stack, KEDA"
	@echo "  deploy       Deploy demo app, load generator, and the predictive scaler"
	@echo "  demo         Run the guided live demo"
	@echo "  port-forward Open Grafana + Prometheus locally"
	@echo "  cluster-down Tear everything down (stops billing)"

sim:
	pip install -e . >/dev/null && python -m sim.compare

test:
	python -m pytest tests/ -q

cluster-up:
	cd terraform && terraform init && terraform apply -auto-approve

kubeconfig:
	aws eks update-kubeconfig --region $(AWS_REGION) --name $(CLUSTER)

addons:
	./scripts/install-addons.sh

deploy:
	./scripts/deploy.sh $(IMAGE)

demo:
	./scripts/demo.sh

port-forward:
	./scripts/port-forward.sh

cluster-down:
	./scripts/teardown.sh
