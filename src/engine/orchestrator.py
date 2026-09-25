import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import json
from collections import defaultdict, deque
from typing import Dict, Any, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

class StateStore:
    def __init__(self):
        self.store = {}

    def set(self, node_id: str, output: Any):
        self.store[node_id] = output

    def get(self, node_id: str) -> Any:
        return self.store.get(node_id)
        
    def get_all(self) -> Dict[str, Any]:
        return self.store

class WorkflowEngine:
    def __init__(self, workflow_json: dict, on_node_status=None):
        self.workflow = workflow_json
        self.nodes = {node['id']: node for node in self.workflow.get('nodes', [])}
        self.edges = self.workflow.get('edges', [])
        self.state = StateStore()
        self.on_node_status = on_node_status

    def topological_sort(self) -> List[str]:
        in_degree = {node_id: 0 for node_id in self.nodes}
        graph = defaultdict(list)
        
        for edge in self.edges:
            source = edge.get('source')
            target = edge.get('target')
            if source in in_degree and target in in_degree:
                graph[source].append(target)
                in_degree[target] += 1
                
        queue = deque([node_id for node_id in in_degree if in_degree[node_id] == 0])
        sorted_nodes = []
        
        while queue:
            current = queue.popleft()
            sorted_nodes.append(current)
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
                    
        if len(sorted_nodes) != len(self.nodes):
            raise ValueError("Cycle detected or disconnected node issue in workflow DAG")
            
        return sorted_nodes

    def run(self):
        sorted_node_ids = self.topological_sort()
        
        for node_id in sorted_node_ids:
            node = self.nodes[node_id]
            if self.on_node_status:
                try:
                    self.on_node_status(node_id, 'running', None)
                except Exception as cb_err:
                    print(f"[WorkflowEngine] Callback error (start): {cb_err}")
            
            self.execute_node(node)
            
            if self.on_node_status:
                try:
                    res = self.state.get(node_id) or {}
                    self.on_node_status(node_id, res.get('status', 'success'), res)
                except Exception as cb_err:
                    print(f"[WorkflowEngine] Callback error (end): {cb_err}")
            
        return self.state.get_all()

    def _find_in_state(self, key: str) -> Any:
        for node_res in self.state.get_all().values():
            if node_res and key in node_res:
                return node_res[key]
        return None

    def execute_node(self, node: dict):
        node_id = node['id']
        node_type = node.get('type')
        # Merge both 'data' and 'config' so settings from frontend are always captured
        node_data = {**(node.get('data') or {}), **(node.get('config') or {})}
        
        inputs = {}
        for edge in self.edges:
            if edge.get('target') == node_id:
                source = edge.get('source')
                inputs[source] = self.state.get(source)
                
        print(f"[WorkflowEngine] Executing node {node_id} of type {node_type} with inputs {inputs}")
        
        try:
            if node_type in ['article-trigger', 'manual-trigger', 'schedule-trigger']:
                topic = (
                    node_data.get('topic') or 
                    node_data.get('topic_title') or 
                    (self.workflow.get('article') or {}).get('title') or 
                    (self.workflow.get('article') or {}).get('topic') or 
                    self.workflow.get('name') or 
                    'AI Trends & Technology'
                )
                article_url = node_data.get('article_url') or (self.workflow.get('article') or {}).get('link') or ''
                category = node_data.get('category') or (self.workflow.get('article') or {}).get('topic') or 'AI'
                viral_score = float(node_data.get('viral_score') or (self.workflow.get('article') or {}).get('score') or 95.0)
                image_url = node_data.get('image_url') or (self.workflow.get('article') or {}).get('image_url') or ''
                
                result = {
                    "status": "success",
                    "node_type": node_type,
                    "topic": topic,
                    "topic_title": topic,
                    "article_url": article_url,
                    "category": category,
                    "score": viral_score,
                    "viral_score": viral_score,
                    "image_url": image_url
                }

            elif node_type == 'gen-script':
                from src.backend.script_gen import generate_video_content
                topic_title = (
                    node_data.get('topic_title') or 
                    node_data.get('topic') or 
                    self._find_in_state('topic_title') or 
                    self._find_in_state('topic') or 
                    (self.workflow.get('article') or {}).get('title') or 
                    (self.workflow.get('article') or {}).get('topic') or 
                    'AI Trends'
                )
                custom_prompt = node_data.get('custom_prompt', '')
                ai_model = node_data.get('model', 'GPT-4o')
                custom_api_key = node_data.get('api_key', '')
                visual_style = node_data.get('visual_style') or self._find_in_state('visual_style') or self.workflow.get('visual_style') or 'cinema_8k'
                
                # Inject hook and viral angle context if available
                hook_text = self._find_in_state('hook') or ''
                viral_angle_text = self._find_in_state('viral_angle') or ''
                
                # Coerce shorts_length string/any type to clean int
                shorts_length_raw = node_data.get('shorts_length', 45)
                try:
                    if isinstance(shorts_length_raw, str):
                        clean_str = "".join(filter(str.isdigit, shorts_length_raw))
                        shorts_length = int(clean_str) if clean_str else 45
                    else:
                        shorts_length = int(shorts_length_raw)
                except Exception:
                    shorts_length = 45

                if hook_text:
                    custom_prompt += f'\n\nSTART WITH THIS EXACT HOOK: "{hook_text}"'
                if viral_angle_text:
                    custom_prompt += f'\nVIRAL ANGLE: {viral_angle_text}'
                custom_prompt += f'\nTARGET LENGTH: {shorts_length} seconds'

                script_data = generate_video_content(
                    topic_title, 
                    custom_prompt, 
                    model_name=ai_model, 
                    custom_api_key=custom_api_key,
                    shorts_length=shorts_length,
                    visual_style=visual_style
                )
                
                result = {
                    "status": "success",
                    "node_type": node_type,
                    "topic": topic_title,
                    "topic_title": topic_title,
                    "visual_style": visual_style,
                    "title": script_data.get('title'),
                    "script": script_data.get('script'),
                    "scenes": script_data.get('scenes', []),
                    "description": script_data.get('description'),
                    "tags": script_data.get('tags')
                }

            elif node_type == 'gen-title':
                topic = self._find_in_state('topic_title') or self._find_in_state('topic') or 'Viral AI Story'
                script_title = self._find_in_state('title') or f"{topic}: The Untold Story"
                result = {"status": "success", "node_type": node_type, "title": script_title}

            elif node_type == 'gen-desc':
                topic = self._find_in_state('topic_title') or self._find_in_state('topic') or 'PulseForge Video'
                desc = self._find_in_state('description') or f"Breaking breakdown of {topic}. Watch till the end to discover what happened next! #Shorts #Trending"
                result = {"status": "success", "node_type": node_type, "description": desc}

            elif node_type == 'gen-tags':
                topic = self._find_in_state('topic_title') or self._find_in_state('topic') or 'AI'
                tags = self._find_in_state('tags') or ["#Shorts", "#Viral", "#AI", "#Trending", f"#{topic.replace(' ', '')[:15]}"]
                result = {"status": "success", "node_type": node_type, "tags": tags}

            elif node_type == 'gen-seo':
                title = self._find_in_state('title') or 'Viral Story'
                desc = self._find_in_state('description') or ''
                tags = self._find_in_state('tags') or []
                result = {"status": "success", "node_type": node_type, "seo_ready": True, "title": title, "description": desc, "tags": tags}
                
            elif node_type == 'tts':
                from src.backend.voice_gen import generate_audio
                script_text = node_data.get('script', '')
                found_script = self._find_in_state('script')
                if found_script:
                    script_text = found_script
                        
                voice = node_data.get('voice', 'en-US-ChristopherNeural')
                output_path = node_data.get('output_path', os.path.join(OUTPUT_DIR, f"audio_{node_id}.mp3"))
                
                audio_path, vtt_path = generate_audio(script_text, output_path, voice)
                if not audio_path:
                    raise ValueError("Audio generation failed")
                    
                result = {
                    "status": "success",
                    "node_type": node_type,
                    "audio_path": audio_path,
                    "subtitle_path": vtt_path
                }
                
            elif node_type in ['image-gen', 'visuals', 'gen-image']:
                from src.backend.image_gen import generate_images_for_scenes
                
                scenes = node_data.get('scenes') or self._find_in_state('scenes')
                if not scenes:
                    raise ValueError("No scenes provided for multi-image generation.")
                
                image_model = node_data.get('model', 'DALL-E 3')
                custom_api_key = node_data.get('api_key', '')
                visual_style = node_data.get('visual_style') or self._find_in_state('visual_style') or 'cinema_8k'
                output_dir = OUTPUT_DIR
                
                updated_scenes = generate_images_for_scenes(
                    scenes, output_dir,
                    model_name=image_model,
                    custom_api_key=custom_api_key,
                    visual_style=visual_style
                )
                
                result = {
                    "status": "success",
                    "node_type": node_type,
                    "scenes": updated_scenes
                }
                
            elif node_type in ['img-to-video', 'image-to-video']:
                from src.backend.video_gen_ai import generate_videos_for_scenes
                
                scenes = node_data.get('scenes') or self._find_in_state('scenes')
                if not scenes:
                    raise ValueError("No scenes provided for image-to-video generation.")
                    
                provider = node_data.get('provider', 'ComfyUI (Local Wan / SVD - Free)')
                api_key = node_data.get('api_key', '')
                output_dir = OUTPUT_DIR
                
                print(f"[Orchestrator] Processing AI Image-to-Video generation using provider: {provider}")
                updated_scenes = generate_videos_for_scenes(
                    scenes=scenes,
                    output_dir=output_dir,
                    provider=provider,
                    api_key=api_key
                )
                            
                result = {
                    "status": "success",
                    "node_type": node_type,
                    "scenes": updated_scenes
                }
                
            elif node_type in ['video-assembler', 'assemble-video']:
                from src.backend.video_assembler import assemble_cinematic_video
                audio_path = node_data.get('audio_path') or self._find_in_state('audio_path')
                subtitle_path = node_data.get('subtitle_path') or self._find_in_state('subtitle_path')
                scenes = node_data.get('scenes') or self._find_in_state('scenes')
                
                music_path = self._find_in_state('music_path')
                sfx_timeline = self._find_in_state('sfx_timeline')
                topic_title = self._find_in_state('topic_title') or self._find_in_state('topic') or 'PulseForge Short'
                viral_score = float(self._find_in_state('score') or 85.0)
                            
                if not audio_path or not scenes:
                    raise ValueError(f"Missing audio or scenes for video-assembler.")
                    
                editing_style = node_data.get('editing_style') or self._find_in_state('editing_style') or self.workflow.get('editing_style') or 'auto'
                output_filename = node_data.get('output_filename', f"video_{node_id}.mp4")
                video_path = assemble_cinematic_video(
                    audio_path, subtitle_path, scenes, output_filename,
                    music_path=music_path, sfx_timeline=sfx_timeline,
                    viral_score=viral_score, topic_title=topic_title,
                    editing_style=editing_style
                )
                
                result = {
                    "status": "success",
                    "node_type": node_type,
                    "video_path": video_path,
                    "saved_locally": True,
                    "output_dir": OUTPUT_DIR
                }
                
            elif node_type in ['youtube-upload', 'upload-yt']:
                from src.backend.youtube_upload import upload_video
                user_id = node_data.get('user_id', 1)
                video_path = node_data.get('video_path') or self._find_in_state('video_path')
                title = node_data.get('title') or self._find_in_state('title') or 'AI Generated Video'
                description = node_data.get('description') or self._find_in_state('description') or ''
                tags = node_data.get('tags') or self._find_in_state('tags') or []
                            
                if not video_path:
                    raise ValueError("No video_path provided for youtube-upload")
                
                try:
                    video_id = upload_video(user_id, video_path, title, description, tags=tags)
                    result = {
                        "status": "success",
                        "node_type": node_type,
                        "video_path": video_path,
                        "saved_locally": True,
                        "youtube_video_id": video_id,
                        "message": f"Successfully uploaded to YouTube (ID: {video_id})"
                    }
                except Exception as upload_err:
                    print(f"[Orchestrator] YouTube upload failed: {upload_err}. Video remains safely saved at {video_path}")
                    result = {
                        "status": "success",  # Keep success status so pipeline does not crash
                        "node_type": node_type,
                        "video_path": video_path,
                        "saved_locally": True,
                        "youtube_video_id": None,
                        "warning": f"YouTube upload skipped/failed ({upload_err}). Video safely saved locally in output folder: {os.path.basename(video_path)}"
                    }
                
            elif node_type == 'extract-viral-angle':
                from src.backend.viral_angle import extract_viral_angle
                topic = node_data.get('topic') or self._find_in_state('topic_title') or self._find_in_state('topic') or 'AI Trends'
                article_summary = self._find_in_state('article_summary') or ''
                model_name = node_data.get('model', 'GPT-4o')
                custom_api_key = node_data.get('api_key', '')
                viral_data = extract_viral_angle(topic, article_summary, model_name, custom_api_key)
                result = {'status': 'success', 'node_type': node_type, **viral_data}

            elif node_type == 'gen-hook':
                from src.backend.hook_gen import generate_hook
                viral_angle_data = self._find_in_state('viral_angle') or {}
                if not viral_angle_data:
                    viral_angle_data = {
                        'emotion': self._find_in_state('emotion') or 'curiosity',
                        'hook_type': self._find_in_state('hook_type') or 'curiosity_gap',
                        'viral_angle': self._find_in_state('viral_angle') or 'AI is changing everything'
                    }
                model_name = node_data.get('model', 'GPT-4o')
                custom_api_key = node_data.get('api_key', '')
                hook = generate_hook(viral_angle_data, model_name, custom_api_key)
                result = {'status': 'success', 'node_type': node_type, 'hook': hook}

            elif node_type == 'bg-music':
                from src.backend.music_engine import get_music_for_emotion
                emotion = node_data.get('emotion') or self._find_in_state('emotion') or 'curiosity'
                music_path = get_music_for_emotion(emotion)
                result = {'status': 'success', 'node_type': node_type, 'music_path': music_path}

            elif node_type == 'gen-sfx':
                from src.backend.sfx_engine import ensure_sfx_assets, build_sfx_timeline
                sfx_map = ensure_sfx_assets()
                scenes = self._find_in_state('scenes') or []
                audio_path = self._find_in_state('audio_path')
                total_duration = 45.0
                if audio_path:
                    try:
                        from moviepy import AudioFileClip
                        with AudioFileClip(audio_path) as clip:
                            total_duration = clip.duration
                    except Exception:
                        pass
                sfx_timeline = build_sfx_timeline(scenes, total_duration)
                result = {'status': 'success', 'node_type': node_type, 'sfx_timeline': sfx_timeline, 'sfx_map': sfx_map}

            elif node_type == 'store-analytics':
                from src.backend.analytics import init_analytics_table, store_video_record
                init_analytics_table()
                topic = self._find_in_state('topic_title') or self._find_in_state('topic') or ''
                hook = self._find_in_state('hook') or ''
                viral_angle = self._find_in_state('viral_angle') or ''
                emotion = self._find_in_state('emotion') or ''
                shorts_length_raw = node_data.get('shorts_length', 45)
                try:
                    if isinstance(shorts_length_raw, str):
                        clean_str = "".join(filter(str.isdigit, shorts_length_raw))
                        shorts_length = int(clean_str) if clean_str else 45
                    else:
                        shorts_length = int(shorts_length_raw)
                except Exception:
                    shorts_length = 45
                video_path = self._find_in_state('video_path') or ''
                model_used = self._find_in_state('model') or 'unknown'
                record_id = store_video_record(topic, hook, viral_angle, emotion, shorts_length, video_path, model_used)
                result = {'status': 'success', 'node_type': node_type, 'record_id': record_id}

            elif node_type == 'audio-agent':
                from src.backend.audio_agent.brain import AudioBrain
                brain = AudioBrain()
                
                viral_angle_data = self._find_in_state('viral_angle') or {}
                if not viral_angle_data:
                    viral_angle_data = {
                        'emotion': self._find_in_state('emotion') or 'curiosity',
                        'hook_type': self._find_in_state('hook_type') or 'curiosity_gap',
                        'viral_angle': self._find_in_state('viral_angle') or 'AI is changing everything'
                    }
                scenes = self._find_in_state('scenes') or []
                
                audio_path = self._find_in_state('audio_path')
                duration_s = 45.0
                if audio_path:
                    try:
                        from moviepy import AudioFileClip
                        with AudioFileClip(audio_path) as clip:
                            duration_s = clip.duration
                    except Exception:
                        pass
                
                audio_res = brain.process_video(viral_angle_data, scenes, duration_s)
                
                bg_music = audio_res.get('background_music')
                music_path = bg_music.get('local_path') if bg_music else None
                
                raw_sfx_timeline = audio_res.get('sfx_timeline') or []
                sfx_timeline = []
                for item in raw_sfx_timeline:
                    sfx_timeline.append({
                        'time': item['time'],
                        'path': item['sound']['local_path'],
                        'volume': item['volume']
                    })
                
                result = {
                    'status': 'success',
                    'node_type': node_type,
                    'music_path': music_path,
                    'sfx_timeline': sfx_timeline,
                    'audio_agent_results': audio_res
                }

            else:
                result = {
                    "status": "success",
                    "node_type": node_type,
                    "processed_data": node_data,
                    "received_inputs": inputs
                }
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[WorkflowEngine] FAILED Node {node_id} ({node_type}): {e}", flush=True)
            result = {
                "status": "error",
                "node_type": node_type,
                "error": str(e)
            }
            
        self.state.set(node_id, result)
