int:docentes;%Numero de docentes
set of 0..5: dias=0..5;%Dias de la semana lunes=0, martes=1, miercoles=2,jueves=3,viernes=4,sabado=5
set of 1..docentes: doc=1..docentes;%set de docentes desde 1 hasta n
int:H;%Cantidad de horas para asignar en los 5 días, 96 horas 6..22 16 por dia
set of 1..H: horas=1..H;%set de horas 1..96
set of int: asi=1..asignaturas;%set de asignaturas
set of 1..6: dasi=1..6;%datos por asignatura [plan,semestre,codigo,grupo,0diurno/1nocturno,semestre]
array[horas,doc] of var bool: D;%matriz de bool horasXdocentes indicando la disponibilidad del docente j en la hora i
array[doc] of set of 1..asignaturas:Da;%array de set de int donde cada posicion indica el set de asignaturas que dicta el docente i
set of int: diurno;%set de enteros que indica si una hora en particular es diurno
set of int: nocturno;%set de enteros que indica si una hora en particular es nocturno
int:asignaturas;%cantidad de asignaturas
array[asi,dasi] of var 0..999999: A;%matriz de asignaturasXdatos donde se tienen los datos de cada una de las asignaturas
array[asi] of var doc: Ad;%array de asignaturas donde el valor del array determina que docente dicta la materia
array[horas,asi] of var bool: C;%matriz de bool horasXasignatura variable de salida que determina las horas donde se dicta la asignatura

%RESTRICCIONES
%constraint forall(a in asi)(sum(h in horas)(if C[h,a] then 1 else 0 endif) = A[a,6]);%Esta es peor
%%%%18623cons - 18410vars - 17752ms
constraint forall(a in asi)(sum(h in horas where C[h,a])(1) = A[a,6]); %la asignacion de horarios para cada materia debe ser igual a su intensida d



%%%Error model inconsistency detected en ambos predicate posiblemente problema con forall 37 bool_ed(false,true)


%los predicate diur y noc verifican que una hora de materia asignada sea diurno o nocturno
%%%%7703cons - 5052vars - 0ms
predicate diur(array[horas] of var bool: hor, var int: inten) =
               (sum(h in horas where  h in diurno /\ hor[h] )(1) = inten);
               
%%%%3300cons - 2140vars - 0ms
predicate noc(array[horas] of var bool: hor, var int: inten) =
               (sum(h in horas where  h in nocturno /\ hor[h])(1) = inten);  
                            
%%%%0cons - 0vars - 9320ms
constraint forall(a in asi)(if A[a,5]=0 then diur(col(C,a),A[a,6])
                                        else noc(col(C,a),A[a,6]) endif);%tipo noc diu para cada asig

%la siguiente restriccion mira todas las asignaturas por cada dia de la semana con lo cual se tiene s como la cantidad de horas que se ve la materia a en el dia d y este s debe ser igual a la intensidad de la materia a en los casos de clases de 2 y 3 horas o 0, mientras que para las materias de 4 horas se pueden ver las 4 horas juntas o se puede ver solo 2 horas en ese día, mientras que si es de 5 horas en un día solo se ven 2 o 3 horas

%%%%18408cons - 12272vars - 25372ms
%%%%3419cons - 1322vars - 168ms
%%%%1784cons - 272vars - 0ms
%%%%368cons - 184vars - 0ms
constraint forall(d in dias, a in asi)(let {var int: s=sum(h in horas where (h-1) div 16 = d /\ C[h,a])(1)} in
                                        (s=0 \/ if A[a,6]<=3 then s=A[a,6] 
                                                            else if A[a,6]=4 then (s=4 /\ junto(col(C,a),d)) \/ s=2 
                                                                            else s=2 \/ s=3 endif endif));
                                                                            
%esta restriccion garantiza que todas las asignaturas que tengan una intensidad horaria superior a 1 que si una materia se ve a la hora h eso implica que la hora siguiente o la anterior debe ser true para esa materia
%%%%4761cons - 0vars - 6136ms
constraint forall(a in asi, h in 2..H-1 where A[a,6]!=1)(C[h,a] -> (C[h+1,a] \/ C[h-1,a]));
%la siguiente funcion valida que para cada materia que tenga intensidad 4 esas cuatro horas tengan que estar juntas, es decir verse las 4 horas seguidas 
%%%%8282cons - 2621vars - 0ms
predicate junto(array[horas] of var bool: hor, var int: di) =
               (forall(h in 4..H-4 where (h-1) div 16 = di /\ hor[h])((hor[h] /\ hor[h+3])\/(hor[h+1] /\ hor[h-1])\/(hor[h] /\ hor[h-3])));  

%restriccion para que si una materia esta asignada a una hora h eso implica que el docente que dicta esa materia tiene disponibilidad a esa hora
%%%%0cons - 0vars - 720ms
constraint forall(h in horas, a in asi)(C[h,a] -> D[h,Ad[a]]);
%garantiza que ningun docente a ninguna hora de más de una clase al tiempo es decir que las materias que dicta el docente no se crucen
%%%%0cons - 0vars - 13851ms
%%%%39821cons - 26774vars - 0ms
constraint forall(d in doc)(forall(h in horas)
                                   (sum(a in Da[d] where a!=0)(if C[h,a] then 1 else 0 endif) <=1));
%mira que no haya cruce entre 2 materias x,y  si pertenecen al mismo programa semestre                             
%%%%0cons - 0vars - 19655ms
%%%%21968cons - 3804vars - 0ms
constraint forall(x,y in asi where x<y /\ A[x,1]=A[y,1] /\ A[x,2]=A[y,2] /\ A[x,3]!=A[y,3])
                      (forall(h in horas where C[h,x])(C[h,x]!=C[h,y]));
                      
%variables objetivo obj1 suma la cantidad de materias que ven clase entre 12 y 14 horas mientras que obj2 mira que calses se ven a las 6 para posteriormente minimizarlas
var int: obj1;
%%%%3077cons - 2828vars - 1131ms
constraint obj1=sum(h in horas, a in asi where C[h,a] /\ ((h mod 16) = 7 \/ (h mod 16) = 8))(1);

var int: obj2;
%%%%1849cons - 1568vars - 596ms
constraint obj2=sum(h in horas, a in asi where C[h,a] /\ (h mod 16) = 1)(1);


solve minimize obj1+obj2;
output ["C=[|"]++[ "" ++ show(C[g,t]) ++ if t = asignaturas then "\n|" else "," endif
       | g in horas, t in asi ] ++ ["];\nmediodia = \(obj1);\n6am = \(obj2);"]
        