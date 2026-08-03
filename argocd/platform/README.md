# Platform runtime layout

`argocd/platform` состоит из двух слоёв:

- `applications/` — только Argo CD `Application` resources и единый
  Kustomize index;
- каталоги компонентов (`authentik/`, `forgejo/`, `gateway/`, `harbor/` и
  другие) — payload, который читают дочерние Applications.

Root Application рендерит `platform/kustomization.yaml`, который подключает
только `applications/`. Файлы в component payload не должны добавляться в
корневой Kustomize напрямую: дочерняя Application владеет их жизненным циклом.

## Добавление компонента

1. Создайте payload в `platform/<component>/` с собственным entrypoint.
2. Добавьте Application manifests в `platform/applications/<component>/`.
3. Зарегистрируйте их в `applications/kustomization.yaml` в порядке
   зависимостей; фактический порядок применения задавайте через sync waves.
4. Добавьте namespace в `AppProject/platform` и обновите environment/OpenBao
   contracts, если компонент использует hostnames или secrets.

Не помещайте runtime manifests в `cluster/` или `infrastructure/`.
