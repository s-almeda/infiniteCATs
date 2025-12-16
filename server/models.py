from dataclasses import dataclass as std_dataclass
from pydantic.dataclasses import dataclass
from typing import List


@dataclass
class Material:
    """Represents a material/element in the game"""
    name: str
    emoji: str
    
    def to_dict(self):
        # Align with API contract expected by frontend/backend cache
        return {"result": self.name, "emoji": self.emoji}
    
    def __eq__(self, other):
        if isinstance(other, Material):
            return self.name.lower() == other.name.lower()
        return False
    
    def __hash__(self):
        return hash(self.name.lower())


@std_dataclass
class Recipe:
    """Represents a recipe/combination of materials"""
    material_list: List[str]
    output: Material
    
    def to_dict(self):
        return {
            "material_list": self.material_list,
            "output": self.output.to_dict()
        }
