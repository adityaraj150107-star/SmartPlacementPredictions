from pydantic import BaseModel, EmailStr, Field
from typing import List, Dict, Optional

class RegisterRequest(BaseModel):
    name:str=Field(min_length=2,max_length=100); email:EmailStr; password:str=Field(min_length=8,max_length=128)
class LoginRequest(BaseModel):
    # Plain string on purpose: strict EmailStr validation rejects reserved domains such as
    # *.local, which would lock out the default admin@smartplacement.local account.
    email:str=Field(min_length=3,max_length=254); password:str=Field(min_length=1,max_length=128)
class VerifyOTPRequest(BaseModel):
    email:EmailStr; otp:str=Field(min_length=6,max_length=6)
class PredictionRequest(BaseModel):
    cgpa:float=Field(ge=0,le=10); tenth:float=Field(ge=0,le=100); twelfth:float=Field(ge=0,le=100)
    aptitude:float=Field(ge=0,le=100); mba_score:float=Field(ge=0,le=100); internship:int=Field(ge=0,le=1)
    hsc_stream:str='Science'; degree_type:str='Sci&Tech'; specialisation:str='Mkt&Fin'; algorithm:str='random_forest'; course:str=Field(default='BCA', max_length=80)
class ChatMessage(BaseModel):
    role:str='user'; content:str
class ChatRequest(BaseModel):
    message:str; context:str=''; history:List[Dict[str,str]]=[]; mode:str='chat'
class ImageRequest(BaseModel):
    prompt:str=Field(min_length=3,max_length=2000); aspect_ratio:str='1:1'; image_size:str='1K'
class AgentChatRequest(BaseModel):
    message:str=Field(default='',max_length=8000); agent:str='smart_placement'; mode:str='chat'
    history:List[Dict[str,str]]=Field(default_factory=list,max_length=20)
    attachment_ids:List[int]=Field(default_factory=list,max_length=5)

class StudentProfileRequest(BaseModel):
    name:str=Field(min_length=2,max_length=100)
    course:str=Field(default='',max_length=80)
    semester:str=Field(default='',max_length=80)
    college:str=Field(default='',max_length=180)
    cgpa:Optional[float]=Field(default=None,ge=0,le=10)
    tenth:Optional[float]=Field(default=None,ge=0,le=100)
    twelfth:Optional[float]=Field(default=None,ge=0,le=100)
    internship:int=Field(default=0,ge=0,le=1)
    skills:str=Field(default='',max_length=2000)
