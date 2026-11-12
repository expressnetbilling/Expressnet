# Kubernetes autoscaling deployment

`web.yaml` creates a Kubernetes Service (the load balancer for ready Django
pods), an Ingress, and an HPA that grows the web deployment from two to twenty
replicas when average CPU reaches 70%.  It requires an installed ingress-nginx
controller and Metrics Server; these are cluster services, not application
dependencies.

Before applying it:

1. Build and publish the application image, then replace the image name/tag in
   `kustomization.yaml` with that immutable tag.
2. Create `expressnet-runtime` from the production environment.  It must at
   least contain the current database, Redis, Django, JWT, and provider
   settings.  Redis must be shared by all replicas because it backs Channels,
   Celery, and the cache.
3. Run database migrations once from CI or a Kubernetes Job.  Do not put
   `migrate` in the scalable web command.
4. Set the production hostname and TLS configuration on the Ingress.

Apply with:

```powershell
kubectl apply -k .\deploy\kubernetes
kubectl get hpa expressnet-web --watch
```

The worker deployment intentionally scales separately from the web deployment.
`expressnet-beat` remains one replica so periodic tasks are not duplicated.
