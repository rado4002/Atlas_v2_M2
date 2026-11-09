"""Run Atlas locally; use ATLAS_DATA_HOME to choose a data profile."""
import os
import uvicorn

if __name__ == '__main__':
    port=int(os.getenv('ATLAS_PORT','8766'))
    print(f'Atlas v2 M1: http://127.0.0.1:{port}')
    print('Ctrl+C stops the server. No cloud or paid AI API required.')
    uvicorn.run('atlas.api:app',host='127.0.0.1',port=port,access_log=False)
