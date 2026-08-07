variable "do_token" {}

provider "digitalocean" {
  token = var.do_token
} 

module "cluster" {
  source = "git::https://github.com/Phazebreak-Coatings-Inc/alembic-environment.git//database/environments/clusters/modules/do/postgres-cluster?ref=main"
  name             = "alembic-environment"
  region           = "nyc1"
  postgres_version = "18"
  size             = "db-s-2vcpu-4gb"
  node_count       = 2
}

module "prod_database" {
  source = "git::https://github.com/Phazebreak-Coatings-Inc/alembic-environment.git//database/environments/clusters/modules/do/postgres-database?ref=main"
  cluster_id = module.cluster.id
  db_name    = "prod"
  user_name  = "prod_user"
}

module "staging_database" {
  source = "git::https://github.com/Phazebreak-Coatings-Inc/alembic-environment.git//database/environments/clusters/modules/do/postgres-database?ref=main"
  cluster_id = module.cluster.id
  db_name    = "staging"
  user_name  = "staging_user"
}

