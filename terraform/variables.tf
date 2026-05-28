variable "aws_region" {
  description = "AWS region for the demo cluster."
  type        = string
  default     = "ap-south-1"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "predictive-autoscaler"
}

variable "cluster_version" {
  description = "EKS control-plane version (pin to your kubectl)."
  type        = string
  default     = "1.32"
}

variable "node_instance_type" {
  description = "Instance type for the demo node group."
  type        = string
  default     = "t3.large"
}

variable "node_min" {
  description = "Min nodes in the managed node group."
  type        = number
  default     = 2
}

variable "node_max" {
  description = "Max nodes — give the autoscaler room to add pods."
  type        = number
  default     = 5
}

variable "node_desired" {
  description = "Desired nodes at start."
  type        = number
  default     = 2
}

variable "tags" {
  description = "Tags applied to all resources (useful for cost tracking)."
  type        = map(string)
  default = {
    Project = "predictive-autoscaler-eks"
    Owner   = "demo"
  }
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDR blocks allowed to reach the EKS public API. Defaults to 0.0.0.0/0 for demo convenience -- for production, set this to your office/VPN egress CIDR."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
