from datetime import datetime

# THis is the main FastAPI app file 
from fastapi import FastAPI, Request, HTTPException, status, Depends
from tortoise.contrib.fastapi import register_tortoise
from models import *  # this import our own custom models from the models.py file

# Authentication
from authentication import*  #(get_password_hash, verify_token)
from fastapi.security import (OAuth2PasswordBearer, OAuth2PasswordRequestForm)

#Signals
from tortoise.signals import post_save
from typing import List, Optional, Type
from tortoise import BaseDBAsyncClient
from mail import *

#Response classes
from fastapi.responses import HTMLResponse

# templates
from fastapi.templating import Jinja2Templates

# Upload files
from fastapi import File, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image
import secrets # for generating unique random file names

# Create FastAPI app
app = FastAPI()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

 # Static files setup config
app.mount("/static", StaticFiles(directory="static"),  name="static")


@app.post("/token")
async def generate_token(request_form: OAuth2PasswordRequestForm = Depends()):
    token = await token_generator(request_form.username, request_form.password)
    return {"access_token": token, "token_type": "bearer"}

async def get_current_user(token: str = Depends(oauth2_scheme)):  # Depends - in Fastapi means this code wont run until that oauth_scheme is executed first
    try:
        payload = jwt.decode(token, config_credentials['SECRET'], algorithms = ['HS256'])
        user = await User.get(id = payload.get("id"))
    except:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED, 
            detail = "Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await user


@app.post('/user/me')
async def user_login(user: user_pydanticIn = Depends(get_current_user)): 
    business = await Business.get(owner = user)
    logo = business.logo
    logo_path = "localhost:8000/static/images/"+logo

    return {
        "status": "Ok",
        "username": user.username,
        "email": user.email,
        "verified": user.is_verified,
        "join_date": user.join_date.strftime("%b %d %Y"),
        "logo_path":logo_path
    }


# Implement signal that is whenever a user account is created/registration then a business object/account will also be create for that user
@post_save(User)
async def create_business(
    sender: "Type[User]", 
    instance: User, 
    created: bool, 
    using_db: "Optional[DBAsyncClient]", 
    update_fields: List[str]
)-> None:
    if created:
        business_obj = await Business.create(
            business_name = instance.username, owner = instance
        )
        await business_pydantic.from_tortoise_orm(business_obj)
        # send the email
        await send_email([instance.email], instance)


#Run the app
@app.post("/registration")
async def user_registration(user: user_pydanticIn):
    user_info = user.dict(exclude_unset=True)
    user_info["password"] = get_password_hash(user_info["password"])   # Encrypt the password

    #Save the user to the database
    user_obj = await User.create(**user_info)
    new_user = await user_pydantic.from_tortoise_orm(user_obj)
    return {
        "status": "ok",
        "data": f"hello {new_user.username}, thanks for choosing our services. Please check your email inbox and click on the link to confirm your registration."
    }


templates = Jinja2Templates(directory="templates")
@app.get("/verification", response_class=HTMLResponse)
async def email_verification(request: Request, token: str):
    user = await verify_token(token)

    if user and not user.is_verified:
        user.is_verified = True
        await user.save()
        return templates.TemplateResponse("verification.html", {"request": request, "username": user.username})
    
    raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

@app.get("/")
def index():
    return {"Message": "Hello Fast API"}

@app.post("/uploadfile/profile")
async def create_upload_file(file: UploadFile = File(...),
                             user: user_pydantic = Depends(get_current_user)):
    FILEPATH = "./static/images/"
    filename = file.filename
    extension = filename.split(".")[1]

    if extension not in ["png", "jpg"]:
        return {"status": "error", "detail": "file extension not allowed"}
    
    token_name = secrets.token_hex(10) + "."+extension
    generated_name = FILEPATH + token_name
    file_content = await file.read()  # reading the content of the file

    with open(generated_name, "wb") as file:
        file.write(file_content)

    #Scaling the file to avoid storing large images
    img = Image.open(generated_name)
    img = img.resize(size=(200, 200))
    img.save(generated_name)

    file.close()

    business = await Business.get(owner = user)
    owner = await business.owner

    if owner == user:
        business.logo = token_name
        await business.save()

    else:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action",
            headers={"WWW-Authenticate": "Bearer"}
        )

    file_url = "localhost:8000" + generated_name[1:]
    return {
        "status": "ok",
        "filename": file_url
    }

# Upload product pictures
@app.post("/uploadfile/produt/{id}")
async def upload_product_image(id: int, file: UploadFile = File(...),
                             user: user_pydantic = Depends(get_current_user)):
    FILEPATH = "./static/images/"
    filename = file.filename
    extension = filename.split(".")[1]

    if extension not in ["png", "jpg"]:
        return {"status": "error", "detail": "file extension not allowed"}
    
    token_name = secrets.token_hex(10) + "."+extension
    generated_name = FILEPATH + token_name
    file_content = await file.read()  # reading the content of the file

    with open(generated_name, "wb") as file:
        file.write(file_content)

    #Scaling the file to avoid storing large images
    img = Image.open(generated_name)
    img = img.resize(size=(200, 200))
    img.save(generated_name)

    file.close()
                             
    product = await Product.get(id = id)
    business = await product.business
    owner = await business.owner

    # Check if the owner of the product is actually the current logged in user
    if owner == user:
        product.product_image = token_name
        await product.save()
    else:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action",
            headers={"WWW-Authenticate": "Bearer"}
        )

    file_url = "localhost:8000" + generated_name[1:]
    return {
        "status": "ok",
        "filename": file_url
    }

# Product CRUD Functionality
@app.post("/products")
async def add_new_product(product: product_pydanticIn, 
                          user: user_pydantic = Depends(get_current_user)):
    product = product.dict(exclude_unset = True)

    business = await Business.get(owner = user)

    # Avoid division error by zero
    if product["original_price"] > 0:
        product["percentage_discount"] = ((product["original_price"] - product["new_price"]) 
                                          / product["original_price"]) * 100
        product_obj = await Product.create(**product, business = business)
        product_obj = await product_pydantic.from_tortoise_orm(product_obj)

        return {"status": "Ok", "data": product_obj}
    else:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail="Error occurred while processing your request"
        )
    

@app.get("/products")
async def get_all_products():
    response = await product_pydantic.from_queryset(Product.all())
    return {"status": "Ok", "data": response}

@app.get("/products/{id}")
async def get_product_by_id(id : int):
    product = await Product.get(id = id)
    business = await product.business
    owner = await business.owner

    response = await product_pydantic.from_queryset_single(Product.get(id = id))

    return {"status": "Ok", 
            "data": {
                "product_details":  response,
                "business_details":{
                    "name": business.business_name,
                    "city": business.city,
                    "region": business.region,
                    "description": business.business_description,
                    "logo": business.logo,
                    "owner_id": owner.id,
                    "email": owner.email,
                    "join_date": owner.join_date.strftime("%b %d %Y")                    
                    }
                }
            
            }

@app.delete("/products/{id}")
async def delete_product(id : int, user : user_pydantic = Depends(get_current_user)):
    product = await Product.get(id = id)
    business = await product.business
    owner = await business.owner

    if user == owner:
        product.delete()
    else:
         raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return {"status": "Ok", "data": "Product deleted"}


# Update product
@app.put("/products/{id}")
async def update_product(id : int,
                            update_info: product_pydanticIn,
                            user: user_pydantic = Depends(get_current_user)):
    product = await Product.get(id = id)
    business = await product.business
    owner = await business.owner

    update_info = update_info.dict(exclude_unset=True)
    update_info["date_published"] = datetime.utcnow()

    if user == owner and update_info["original_price"] !=0:
        update_info["percentage_discount"] = ((update_info["original_price"] - update_info["new_price"]) / update_info["original_price"]) * 100
        updated_product = await product.update_from_dict(update_info)
        await updated_product.save()
        response = await product_pydantic.from_tortoise_orm(product)
        return {"status": "Ok", "data": response}
    else:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action or invalid user input",
            headers={"WWW-Authenticate": "Bearer"}
        )
    

# Update business
@app.put("/business/{id}", tags=["Update business"])
async def update_business(id : int,
                            update_business: business_pydanticIn,
                            user: user_pydantic = Depends(get_current_user)):
    
    update_business = update_business.dict()
    business = await Business.get(id = id)
    business_owner = await business.owner

    if user == business_owner:
        updated_business = await business.update_from_dict(update_business)
        await updated_business.save()
        response = await business_pydantic.from_tortoise_orm(business)
        return {"status": "Ok", "data": response}
    else:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action",
            headers={"WWW-Authenticate": "Bearer"}
        )

register_tortoise(
    app, 
    db_url = "sqlite://database.sqlite3",
    modules = {"models" : ["models"]},
    generate_schemas=True,
    add_exception_handlers=True
)






