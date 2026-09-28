
## Quickstart

```copier-template``` creates an out-of-the-box repo for creating copier projects with easy consumer apis.

### Creating Your Copier Repo

First we'll create a uv workspace.

```sh
uv init
```

Then we'll use ```uvx``` to copy the template into it.

```sh
uvx copier-template init
```

```uv init``` creates ```.python-version``` and ```README.md```. The template has its own copies, so copier asks to overwrite them. Answer ```y``` to both.

If you need to update, check:

```sh
uvx {{ project_name }} update
```

Add ```--defaults``` to reuse your previous answers without prompting. This is needed in CI or any shell without a terminal:

```sh
uvx {{ project_name }} update --defaults
```

On ```init```, ```--defaults``` only works for questions that have a default. Questions without one, like ```github_repo```, still need an answer.


!!! Warning

   Docs are coming soon. Thanks for your patience. 
