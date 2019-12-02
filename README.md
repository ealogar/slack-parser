# slack-messages-by-user
Es un pequeño script para hacer búsquedas agregadas en un canal de slack, agrupadas por usuario y con la posibilidad
de filtrar por reaction o por una expresión regular.

# Features
- Límite de búsqueda por fechas
- Busqueda agregada por usuario en un canal
    - filtrando por reaction
    - filtrando por expresión regular
    - Incluyendo threads (not supported)
- Búsqueda agregada por resultado de aplicar una expresión regular en un canal
    - Incluyendo threads (ralentiza la operación)
- métodos para imprimir los resultados

# Requisitos
- Tener un SLACK_API_TOKEN, que se puede conseguir mediante una app a la que se le den los scopes de Oauth2 siguientes:
   - channels:history
   - channels:read
   - search:read
   - users.profile:read
   - users:read

# Instalación
- Instalar los requirements:
```bash
pip install -r requirements.txt
```
- Tener en el pythonpath el script slack-messages o ejecutar una consola python en el directorio directamente

# Ejemplos de uso
- definir las variables de entorno 
```bash
source env.sh
```

Ejecutar un intérprete de python o directamente cambiar la función main
```python
from slack_messages import *
slack_token = os.environ["SLACK_API_TOKEN"]
channel_name = os.environ["SLACK_CHANNEL_NAME"]
date_from = os.environ["SLACK_SEARCH_FROM"]
date_to = os.environ["SLACK_SEARCH_TO"]
sc = slack.WebClient(slack_token)
users = get_users(sc)
channel_id = get_channel_id(sc, channel_name)
posts_by_user = get_aggregated_posts_by_user(sc, channel_id, date_from, reaction_filter=None, post_regexp_filter='nos vamos a salir')
pretty_print_aggregated_posts(users, posts_by_user, channel_name)
```

Hay más ejemplos comentados en el main...
