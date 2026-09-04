This directory is for referencing modules that might be updated, without clients having to run ```update```.

Recommended structure for creating modules within this directory, from (Hashicorp documentation)[https://developer.hashicorp.com/terraform/language/modules/develop/structure]:

> A minimal recommended module following the standard structure is shown below. While the root module is the only required element, we recommend the structure below as the minimum:
>
>``` $ tree minimal-module/
> .
>├── README.md
>├── main.tf
>├── variables.tf
>├── outputs.tf
>```

Clients in your template should reference your public repository if using terraform modules you provide in your template:

```terraform
module "auth0" {
  source = "git::https://github.com/<user>/<repo>.git//terraform/modules/auth0?ref=v0.1.0"

  project_name = var.project_name
  api_domain   = var.api_domain
}
```

Always pin `?ref=` to a tag to pin a version. 
