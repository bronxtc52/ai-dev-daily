import pathlib
import sys

# Тесты обращаются к модулям пайплайна так же, как это делает runtime:
# скрипты запускаются из pipeline/, поэтому каталог лежит в пути импорта.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "pipeline"))
