output "database_host" {
  value = module.cluster.host
}

output "database_port" {
  value = module.cluster.port
}

output "prod_username" {
  value = module.prod_database.user_name
}

output "prod_password" {
  sensitive = true
  value     = module.prod_database.user_password
}

output "prod_name" {
  value = module.prod_database.db_name
}

output "staging_username" {
  value = module.staging_database.user_name
}


output "staging_password" {
  sensitive = true
  value     = module.staging_database.user_password
}

output "staging_name" {
  value = module.staging_database.db_name
}

output "admin_username" {
  value = module.cluster.admin_username
}

output "admin_password" {
  sensitive = true
  value     = module.cluster.admin_password
}
