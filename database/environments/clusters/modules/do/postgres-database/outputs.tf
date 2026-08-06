output "db_name" {
  value = digitalocean_database_db.alembic_environment_database.name
}

output "user_name" {
  value = digitalocean_database_user.alembic_environment_database_user.name
}

output "user_password" {
  sensitive = true
  value     = digitalocean_database_user.alembic_environment_database_user.password
}
