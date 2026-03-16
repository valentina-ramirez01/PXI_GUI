
If you ever get this error:

```
.\.venv\Scripts\Activate.ps1 : File C:\Users\pxiepython\PXI_GUI\.venv\Scripts\Activate.ps1 cannot be 
loaded because running scripts is disabled on this system. For more information, see 
about_Execution_Policies at https:/go.microsoft.com/fwlink/?LinkID=135170.
At line:1 char:1
+ .\.venv\Scripts\Activate.ps1
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : SecurityError: (:) [], PSSecurityException
    + FullyQualifiedErrorId : UnauthorizedAccess
```

run this

```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```


to run the docker

```
docker build -t pxi_communication .
```

```
docker build -t pxi_communication . --progress=plain
```
to run the executable

```
cd path\to\your\project\dist
.\dist\demo.exe

After it runs go to:
http://127.0.0.1:8050

```
