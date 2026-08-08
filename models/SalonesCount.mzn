%Conjunto de los recursos
enum Recursos;
int:sede;
int:salones;
set of int: sal=1..salones;
array[sal] of var int: Sc;
array[sal] of var Recursos: Sr;
int:N;
int:Asig;
int:ini;%indica a partir de que asignatura se evalua
int:fin;%indica hasta cual asignatura se evalua
set of int: asi=ini..fin;%rango de asignaturas determinado
set of int: asit=1..Asig;%todas las asginaturas
%enum A;
array[asit] of var Recursos: Ar;
array[asit] of var int: Ae;
set of int: horas=1..N;
array[horas,asit] of var bool: C;%Matriz horas por asignatura con true si se ve clase en esa hora
array[horas,sal] of var 0..Asig: SAO;%Matriz de salida con los id de asignaturas en los salones
array[horas,sal] of var 0..Asig: SAI;%Matriz de entrada con los id de asignaturas

%asigna las materias que fueron asignadas previamente a la matriz con la que se trabaja actualmenete
constraint forall(h in horas, s in sal where SAI[h,s]!=0)(SAO[h,s]=SAI[h,s]);

%include "global_cardinality.mzn";
%  constraint forall(h in horas, a in asi)(if C[h,a] 
%                                            then global_cardinality(row(SA,h),[a],[1])
%                                            else global_cardinality(row(SA,h),[a],[0])
%                                            endif);
% % constraint forall(a in asit,h in horas, s in sal where C[h,a] )(if a =1 then count(row(SA,h),a)=1
% else 1=1 endif);

%garantiza que no haya una materia asignada en mas de un salon
constraint forall(h in horas, a in asi where C[h,a])(count(row(SAO,h),a)=1);

%include "alldifferent_except_0.mzn";

%constraint forall(h in horas)(alldifferent_except_0(row(SAO,h)));

%Las siguientes restricciones se unieron en una sola pero lo que miran es que el recurso de la materia sea igual al salon y que la capacidad del salon sea mayor o igual al de la materia
%%%constraint forall(h in horas,s in sal, a in asi)(SA[h,s]=a -> (C[h,a] /\ (Ar[a]=Recursos[3] \/ Ar[a]=Sr[s])));
%constraint forall(h in horas,s in sal, a in asi where SAO[h,s]=a /\ C[h,a])(Ar[a]=Sr[s]);
%constraint forall(h in horas,s in sal, a in asi where SAO[h,s]=a /\ C[h,a])(Sc[s]>=Ae[a]);
%constraint forall(h in horas,s in sal, a in asi where SAO[h,s]=a  /\ C[h,a] /\  Sc[s]>=Ae[a] /\ Ar[a]=Sr[s])( true );
constraint forall(h in horas,s in sal, a in asi where SAO[h,s]=a  /\ C[h,a]  )( Sc[s]>=Ae[a] /\ Ar[a]=Sr[s] );
%constraint forall(h in horas,s in sal, a in asi where SAO[h,s]=a  /\ C[h,a] /\  Sc[s]>=Ae[a] /\ Ar[a]=Sr[s])( true );
%constraint forall(h in horas,s in sal, a in asi where SAO[h,s]=a  /\ C[h,a] /\  Sc[s]>=Ae[a])( Ar[a]=Sr[s] );



constraint forall(h in horas, s in sal where SAO[h,s]>0)(C[h,SAO[h,s]]);


%que las materias que se asignan estén en el mismo salon si están en el mismo dia
constraint forall(h in 1..N-1, s in sal, a in asi where C[h,a] /\ C[h+1,a] /\ SAO[h,s]=a )( SAO[h+1,s]=a);

%funcion para calcular la cantidad de salones libres
%%predicate slib(array[horas] of var 0..Asig: salon) =
 %%              (sum(h in horas where salon[h]=0)(1) = N);
var 0..salones: libres;
%constraint libres = sum(s in sal where slib(col(SAO,s)))(1);
constraint libres = sum(s in sal where count(col(SAO,s),0)=N)(1);
solve maximize libres ;
output ["SAI=[|"] ++ [ " " ++ show_int(3,SAO[g,t]) ++ if t = salones then "\n|" else "," endif
       | g in horas, t in sal ] ++ ["];\nlibres = \(libres)"]