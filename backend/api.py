
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from backend.core_logic.app_funscript_processor import AppFunscriptProcessor
from backend.core_logic.app_stage_processor import AppStageProcessor
from backend.core_logic.preview_generator import PreviewGenerator
from backend.core_logic.tensorrt_compiler_logic import TensorRTCompiler
from backend.core_logic.app_file_manager import AppFileManager

class FunGenAPI:
    def __init__(self):
        self.funscript_processor = AppFunscriptProcessor(self)
        self.stage_processor = AppStageProcessor(self)
        self.preview_generator = PreviewGenerator(self)
        self.tensorrt_compiler = TensorRTCompiler(self)
        self.file_manager = AppFileManager(self)

    def get_funscript_processor(self):
        return self.funscript_processor

    def get_stage_processor(self):
        return self.stage_processor

    def get_preview_generator(self):
        return self.preview_generator

    def get_tensorrt_compiler(self):
        return self.tensorrt_compiler

    def get_file_manager(self):
        return self.file_manager

if __name__ == '__main__':
    api = FunGenAPI()
    print("FunGen API initialized successfully.")
