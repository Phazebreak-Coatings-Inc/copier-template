variable "name" {}
variable "region" {}

variable "postgres_version" {
  default = "18"
}

variable "size" {
  default = "db-s-1vcpu-2gb"
}

variable "node_count" {
  default = 1
}

variable "firewall_rules" {
  description = "Trusted sources; type is ip_addr, droplet, app, k8s, or tag. Empty list = no firewall (cluster open to the internet)."
  type = list(object({
    type  = string
    value = string
  }))
  default = []
}
