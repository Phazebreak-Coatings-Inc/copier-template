resource "digitalocean_database_db" "alembic_environment_database" {
  cluster_id = var.cluster_id
  name       = var.db_name
}

resource "digitalocean_database_user" "alembic_environment_database_user" {
  cluster_id = var.cluster_id
  name       = var.user_name

  lifecycle {
    ignore_changes = [settings]
  }
}
