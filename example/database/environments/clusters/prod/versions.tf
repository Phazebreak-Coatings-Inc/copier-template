terraform {
  required_version = ">= 1.9"
  cloud {}
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}
