With ```alembic-environment```, prebuilt database environments are already available to you. The prebuilt ones are ```dev```, ```staging```, and ```prod```. ```dev``` is a locally run postgres container, whereas ```prod``` and ```staging``` are different databases on a Digital Ocean Cluster. Uses ```postgres 18```

## Local environments

### Setting Up ```dev```

To setup your ```dev``` environment. We don't need to pass any kind of environment variables, everything already comes out of the box.

Run the following command to bring up your database:

```uv run python -m environments up dev```

```
PS C:\Users\miles\PycharmProjects\alembic-environment> uv run python 
-m environments up dev
[+] up 2/2
 ✔ Network dev_default              Created                      0.0s
 ✔ Container postgres_dev_container Created                      0.1s
Waiting for dev_db (1/60)...
dev_db ready in 549ms
Running startup steps... [1/2]
Imported 'models' successfully.
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.       
INFO  [alembic.runtime.migration] Will assume transactional DDL.     
Running startup steps... [2/2]
Found 0 seeds for environment 'dev'...
Completed 2 steps successfully.
```

You'll notice the process closes after pinging the database and running ```alembic upgrade head```. No worries! It runs detached, so we don't have to babysit the command line.

Let's go ahead and ping it after to make sure everything's okay:

```
PS C:\Users\miles\PycharmProjects\alembic-environment> uv run python 
-m environments ping dev
dev_db ready in 26ms
```

## Cloud Environments

### Remote State

Because our cloud environments use ```terraform```, we'll want to create a remote state for the resources we provision.

You'll need to first go to [HCP Terraform](https://app.terraform.io/app), sign up, then create an organization, and finally, a workspace.

After, read the documentation [here](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/api-tokens) to create a token.

Once signed up, run ```terraform login```:

```
Terraform will store the token in plain text in the following file   
for use by subsequent commands:
    C:\Users\miles\AppData\Roaming\terraform.d\credentials.tfrc.json 

Token for app.terraform.io:
  Enter a value:
```

Enter the token you just created.

After, refer to the ```./.env.api``` for entering the following environment variables:

```
TF_CLOUD_ORGANIZATION="Your Hashicorp organization here"
TF_WORKSPACE="Your project name here"
```

### Setting Up ```prod``` and ```staging```

First, we'll want to create a Personal Access Token for Digital Ocean. Please visit the following documentation for steps to retrieve it [here](https://docs.digitalocean.com/reference/api/create-personal-access-token/).

Once you have your token, create and open your env file at ```./.env```:

```
TF_VAR_do_token="{{Your digital ocean token here}}"
```

Once you have listed your token under ```TF_VAR_do_token```, go ahead and terraform your database environments using the following command:

```
uv run --env-file .env python -m environments up prod
```

It will alert us that we're successfully connected to the cloud:

```
HCP Terraform has been successfully initialized!
```

It will also alert us to the following resources that will be created:

```
Terraform will perform the following actions:

  # module.cluster.digitalocean_database_cluster.alembic_environment_
database_cluster will be created
  + resource "digitalocean_database_cluster" "alembic_environment_dat
abase_cluster" {
      + database             = (known after apply)
      + engine               = "pg"
      + host                 = (known after apply)
      + id                   = (known after apply)
      + metrics_endpoints    = (known after apply)
      + name                 = "alembic-environment"
      + node_count           = 2
      + password             = (sensitive value)
      + port                 = (known after apply)
      + private_host         = (known after apply)
      + private_network_uuid = (known after apply)
      + private_uri          = (sensitive value)
      + project_id           = (known after apply)
      + region               = "nyc1"
      + size                 = "db-s-2vcpu-4gb"
      + storage_size_mib     = (known after apply)
      + ui_database          = (known after apply)
      + ui_host              = (known after apply)
      + ui_password          = (sensitive value)
      + ui_port              = (known after apply)
      + ui_uri               = (sensitive value)
      + ui_user              = (known after apply)
      + uri                  = (sensitive value)
      + urn                  = (known after apply)
      + user                 = (known after apply)
      + version              = "18"
    }

  # module.prod_database.digitalocean_database_db.alembic_environment
_database will be created
  + resource "digitalocean_database_db" "alembic_environment_database
" {
      + cluster_id = (known after apply)
      + id         = (known after apply)
      + name       = "prod"
    }

  # module.prod_database.digitalocean_database_user.alembic_environme
nt_database_user will be created
  + resource "digitalocean_database_user" "alembic_environment_databa
se_user" {
      + access_cert = (sensitive value)
      + access_key  = (sensitive value)
      + cluster_id  = (known after apply)
      + id          = (known after apply)
      + name        = "prod_user"
      + password    = (sensitive value)
      + role        = (known after apply)
    }

  # module.staging_database.digitalocean_database_db.alembic_environm
ent_database will be created
  + resource "digitalocean_database_db" "alembic_environment_database
" {
      + cluster_id = (known after apply)
      + id         = (known after apply)
      + name       = "staging"
    }

  # module.staging_database.digitalocean_database_user.alembic_enviro
nment_database_user will be created
  + resource "digitalocean_database_user" "alembic_environment_databa
se_user" {
      + access_cert = (sensitive value)
      + access_key  = (sensitive value)
      + cluster_id  = (known after apply)
      + id          = (known after apply)
      + name        = "staging_user"
      + password    = (sensitive value)
      + role        = (known after apply)
    }

Plan: 5 to add, 0 to change, 0 to destroy.

Changes to Outputs:
  + database_host    = (known after apply)
  + database_port    = (known after apply)
  + prod_name        = "prod"
  + prod_password    = (sensitive value)
  + prod_username    = "prod_user"
  + staging_name     = "staging"
  + staging_password = (sensitive value)
  + staging_username = "staging_user"
```

The database cluster can up to 10 minutes to provision. Don't cancel the current command.

If you want to destroy your infrastructure, run ```uv run --env-file .env python -m environments down prod --destroy```.

## Applying Migrations

If you want to apply a migration to prod or staging there are two methods:

### Manually

We'll use ```migrations``` to apply a migration to a specific environment.

```uv run --env-file .env python -m migrations apply prod```

The following output:

```
Upgrade prod to head? [y/N]: y
Imported 'models' successfully.
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DD
L.
```

### Via ```--startup```

We can use the ```--startup``` flag to call startup steps on whichever environment we want.

```uv run --env-file .env python -m environments up --startup```

!!! Warning
    
    This will also seed the database, and run whatever other startup steps there are.

```
Database 'prod' is already up.
Running startup steps... [1/3]
Ensured grant on schema public to prod_user
Running startup steps... [2/3]
Imported 'models' successfully.
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DD
L.
Running startup steps... [3/3]
Found 0 seeds for environment 'prod'...
Completed 3 steps successfully.
```


## Accessing The Databases

### Accessing via Python

If you'd like to access your infrastructure in python, do the following:

```python
from database_core import get_database_setting

engine = get_database_setting("prod").engine
```

```engine``` provides ```SQLAlchemy```'s ```Engine``` object.

If you'd like to access a different engine, replace ```"prod"``` with either ```"dev"``` or ```"staging"```.

You can even set which environment is running with environment variables:

```python
import os
from database_core import get_database_setting

env = os.environ.get("ENVIRONMENT")
engine = get_database_setting(env).engine
```

```get_database_setting()``` automatically validates with ```pydantic```, so if you put an invalid value, there's nothing to worry about.

### Querying via CLI

If you want to query a database environment directly, use the following:

```uv run --env-file .env python -m environments exec```

We can either feed the command SQL or the name of a ```.sql``` file.

For example, let's run a simple query:

```sql
SELECT 1
```

```
uv run --env-file .env python -m environments exec dev --sql "SELECT 1"
```

The output:

```
{'?column?': 1}
1 row(s)
```

We can do the same thing by making a ```.sql``` file called ```select.sql``` and putting ```SELECT 1``` there.

```
uv run --env-file .env python -m environments exec dev --file "./select.sql"
```

The output, again:

```
{'?column?': 1}
1 row(s)
```

You can also run this on the ```staging``` and ```prod``` environments, but they will ask you to confirm your execution:

```
uv run --env-file .env python -m environments exec prod --file "./select.sql"
```

```
Run against 'prod'?

SELECT 1;

 [y/N]: y
{'?column?': 1}
1 rows(s)
```
