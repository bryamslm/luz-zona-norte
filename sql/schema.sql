-- Modelo estrella de continuidad electrica en SQL Server (T-SQL). Lo ejecuta
-- scripts/cargar.py; es idempotente: borra y recrea el esquema dw.
-- Los lotes se separan con GO (cargar.py los parte).

if schema_id('dw') is not null
begin
  declare @sql nvarchar(max) = N'';
  select @sql += N'drop view dw.' + quotename(name) + N';' from sys.views where schema_id = schema_id('dw');
  exec sp_executesql @sql;
  set @sql = N'';
  -- primero las llaves foraneas: asi el orden de borrado de tablas no importa
  select @sql += N'alter table dw.' + quotename(object_name(parent_object_id)) + N' drop constraint ' + quotename(name) + N';'
  from sys.foreign_keys where schema_id = schema_id('dw');
  exec sp_executesql @sql;
  set @sql = N'';
  select @sql += N'drop table dw.' + quotename(name) + N';' from sys.tables where schema_id = schema_id('dw');
  exec sp_executesql @sql;
  drop schema dw;
end
GO
create schema dw;
GO

-- Dimensiones ----------------------------------------------------------------

create table dw.dim_periodo (
  id_periodo int          not null primary key,   -- AAAAMM
  anio       int          not null,
  mes        int          not null check (mes between 1 and 12),
  nombre_mes nvarchar(12) not null,
  fecha      date         not null                -- primer dia del mes
);

create table dw.dim_empresa (
  cod_empresa  nvarchar(20)  not null primary key,
  empresa      nvarchar(40)  not null,
  razon_social nvarchar(120) not null
);

-- Definicion oficial: plantilla PCE 05 de ARESEP, hoja CATALOGO TIPO DE INDICADOR.
create table dw.dim_tipo (
  tipo        int           not null primary key,
  nombre      nvarchar(40)  not null,
  descripcion nvarchar(300) not null
);

create table dw.dim_circuito (
  id_circuito int           not null primary key,
  cod_empresa nvarchar(20)  not null references dw.dim_empresa,
  circuito    nvarchar(80)  not null,             -- nombre normalizado (mayusculas, sin tildes)
  nombre      nvarchar(80)  not null,
  primer_anio int           not null,
  ultimo_anio int           not null,
  unique (cod_empresa, circuito)
);

create table dw.dim_distrito (
  cod_distrito     int          not null primary key,  -- codigo DTA del IGN
  provincia        nvarchar(60) not null,
  canton           nvarchar(60) not null,
  distrito         nvarchar(80) not null,
  pct_en_concesion decimal(5,4) not null              -- parte del distrito dentro de la concesion
);

create table dw.dim_planta (
  planta      nvarchar(40) not null primary key,
  cod_empresa nvarchar(20) not null references dw.dim_empresa
);

-- Hechos ---------------------------------------------------------------------

-- Una fila por circuito, periodo y tipo de indicador. `meses` = 1 (reporte mensual)
-- o 6 (semestral, en junio y diciembre). Los productos *_x_abon permiten agregar:
-- FPI de un grupo = sum(fpi_x_abon) / abonados promedio.
create table dw.fact_continuidad (
  id_periodo  int           not null references dw.dim_periodo,
  cod_empresa nvarchar(20)  not null references dw.dim_empresa,
  id_circuito int           not null references dw.dim_circuito,
  tipo        int           not null references dw.dim_tipo,
  fpi         decimal(10,4) not null,   -- interrupciones por abonado
  dpir        decimal(10,4) not null,   -- horas de interrupcion por abonado
  abonados    int           not null,
  fpi_x_abon  decimal(18,4) not null,
  dpir_x_abon decimal(18,4) not null,
  meses       int           not null check (meses in (1, 6)),
  primary key (id_periodo, id_circuito, tipo)
);

create table dw.fact_lluvia (
  cod_distrito int          not null references dw.dim_distrito,
  id_periodo   int          not null references dw.dim_periodo,
  mm_era5      decimal(8,1) null,      -- Open-Meteo (ERA5): fuente principal
  mm_merra2    decimal(8,1) null,      -- NASA POWER (MERRA-2): solo contraste
  primary key (cod_distrito, id_periodo)
);

create table dw.fact_generacion (
  id_periodo int           not null references dw.dim_periodo,
  planta     nvarchar(40)  not null references dw.dim_planta,
  kwh        decimal(18,2) not null,
  primary key (id_periodo, planta)
);
GO

-- Vistas (la misma logica vive en DAX; aca sirve para validar el tablero) ------

-- Indicadores anuales por empresa y descomposicion por causa.
create view dw.v_continuidad_empresa_anual as
with ab as (   -- abonados promedio de los periodos que la empresa reporto
  select p.anio, f.cod_empresa, avg(cast(f.ab as float)) as abonados
  from (select id_periodo, cod_empresa, sum(abonados) as ab
        from dw.fact_continuidad where tipo = 1 group by id_periodo, cod_empresa) f
  join dw.dim_periodo p on p.id_periodo = f.id_periodo
  group by p.anio, f.cod_empresa
), s as (
  select p.anio, f.cod_empresa,
         sum(case when tipo = 1 then fpi_x_abon end)  as fpi1,
         sum(case when tipo = 2 then fpi_x_abon end)  as fpi2,
         sum(case when tipo = 3 then fpi_x_abon end)  as fpi3,
         sum(case when tipo = 1 then dpir_x_abon end) as dpir1
  from dw.fact_continuidad f join dw.dim_periodo p on p.id_periodo = f.id_periodo
  group by p.anio, f.cod_empresa
)
select s.anio, s.cod_empresa, ab.abonados,
       s.fpi1 / ab.abonados                as fpi_total,
       s.dpir1 / ab.abonados               as dpir_total,
       (s.fpi1 - s.fpi2) / ab.abonados     as fpi_ice,
       (s.fpi2 - s.fpi3) / ab.abonados     as fpi_externas,
       s.fpi3 / ab.abonados                as fpi_internas,
       (s.fpi2 - s.fpi3) / nullif(s.fpi1, 0) as pct_externas
from s join ab on ab.anio = s.anio and ab.cod_empresa = s.cod_empresa;
GO

-- Lluvia mensual promedio de la zona de concesion de Coopelesca.
create view dw.v_lluvia_zona as
select id_periodo, avg(mm_era5) as mm_era5, avg(mm_merra2) as mm_merra2
from dw.fact_lluvia group by id_periodo;
GO

-- Acceso de solo lectura para Power BI.
grant select on schema::dw to luz_bi;
