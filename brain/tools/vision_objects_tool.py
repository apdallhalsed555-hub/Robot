"""
brain/tools/vision_objects_tool.py
Tool to allow the LLM to query the live camera feed and see detected objects.
"""

class VisionObjectsTool:
    def __init__(self, vision_pipeline=None):
        self.vision = vision_pipeline

    def detect_visible_objects(self) -> str:
        """
        Queries the robot's active camera and returns the list of objects currently visible in the scene.
        """
        if not self.vision:
            return "Error: Vision system is not initialized."
        
        try:
            scene = self.vision.get_latest_scene()
            if not scene or not scene.objects:
                return "I do not see any objects in my view right now."
            
            obj_counts = {}
            for obj in scene.objects:
                name = obj.class_name
                obj_counts[name] = obj_counts.get(name, 0) + 1
            
            summary = []
            for name, count in obj_counts.items():
                unit = "instance" if count == 1 else "instances"
                summary.append(f"{count} {name}(s)")
                
            obj_strings = [f"- {obj.class_name} (Confidence: {obj.confidence:.2f})" for obj in scene.objects]
            
            return (
                f"I currently see: {', '.join(summary)}.\n"
                f"Full details:\n" + "\n".join(obj_strings)
            )
        except Exception as e:
            return f"Error reading objects from camera: {e}"
