param(
    [Parameter(Mandatory=$true)]
    [string]$Name
)

$ModuleDir = "app\modules\$Name"

if (Test-Path $ModuleDir) {
    Write-Error "Module '$Name' already exists at $ModuleDir"
    exit 1
}

Write-Host "Creating module: $Name" -ForegroundColor Green

# Create directories
New-Item -ItemType Directory -Path $ModuleDir -Force | Out-Null

# __init__.py
"" | Out-File -FilePath "$ModuleDir\__init__.py" -Encoding utf8

# models.py
@"
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class $(Get-Culture).TextInfo.ToTitleCase($Name)Base(Base):
    __tablename__ = "$($Name)s"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True))
"@ | Out-File -FilePath "$ModuleDir\models.py" -Encoding utf8

# schemas.py
@"
from pydantic import BaseModel


class $(Get-Culture).TextInfo.ToTitleCase($Name)Base(BaseModel):
    pass
"@ | Out-File -FilePath "$ModuleDir\schemas.py" -Encoding utf8

# service.py
@"
from sqlalchemy.ext.asyncio import AsyncSession


async def get_all(db: AsyncSession):
    pass
"@ | Out-File -FilePath "$ModuleDir\service.py" -Encoding utf8

# router.py
@"
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db

router = APIRouter(prefix="/api/v1/$Name", tags=["$Name"])


@router.get("/")
async def list_$Name(db: AsyncSession = Depends(get_db)):
    return {"module": "$Name"}
"@ | Out-File -FilePath "$ModuleDir\router.py" -Encoding utf8

Write-Host ""
Write-Host "Done! Module created at: $ModuleDir" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Edit $ModuleDir/models.py - define your tables"
Write-Host "  2. Edit $ModuleDir/schemas.py - define request/response shapes"
Write-Host "  3. Edit $ModuleDir/service.py - write business logic"
Write-Host "  4. Edit $ModuleDir/router.py - define endpoints"
Write-Host "  5. Register in app/main.py: from .modules.$Name.router import router as ${Name}_router"
Write-Host "  6. Register in alembic/env.py: from app.modules.$Name import models"
Write-Host "  7. Run: uv run alembic revision --autogenerate -m 'create $Name table'"
Write-Host "  8. Run: uv run alembic upgrade head"
