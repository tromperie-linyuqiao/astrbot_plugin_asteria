'use strict';
window.AsteriaBrand={"name":"Asteria Chat"};
document.addEventListener('DOMContentLoaded',()=>{const name=window.AsteriaBrand.name;document.title=name;const brand=document.querySelector('.brand strong');if(brand)brand.textContent=name;const about=document.querySelector('.about-app>span');if(about&&about.firstChild)about.firstChild.textContent=name+' ';},{once:true});
