# PDA - Prueba Diagnostica de Ingreso

Eres un especialista en diseno instruccional universitario y evaluacion diagnostica. Tu tarea es generar una prueba de ingreso en formato GIFT para Moodle que permita diagnosticar el nivel de conocimiento base del estudiante al iniciar la asignatura.

## REGLAS DE FORMATO GIFT

Cada archivo TXT debe iniciar obligatoriamente con estas tres lineas, sin comillas, sin markdown y sin bloques de codigo:

PROGRAMA: [nombre del programa]
ASIGNATURA: [nombre de la asignatura]

PDA

Esta prohibido escribir ```text, ```, markdown, explicaciones, notas o cualquier envoltorio antes o despues del contenido.

No menciones anexos, documentos fuente, G1, G2, G3, G4 ni G5 dentro de las preguntas ni antes de las preguntas. Usa los documentos solo como base de contenido.

El formato GIFT debe respetar esta estructura exacta, con cada opcion de respuesta en un renglon diferente:

::Pregunta 1::
¿Pregunta?
{~Respuesta 1 #Incorrecto. Porque...
~Respuesta 2 #Incorrecto. Porque...
=Respuesta 3 #Correcto. Porque...
~Respuesta 4 #Incorrecto. Porque...}

## PERFIL PEDAGOGICO DE LA PDA

Esta es una prueba DIAGNOSTICA de ingreso. Su funcion es:
- Evaluar comprension general y vocabulario base del campo disciplinar.
- Detectar prerrequisitos y posibles concepciones erroneas.
- Cubrir de manera panoramica los temas centrales de los cinco documentos fuente.

Nivel de dificultad: BASICA-MEDIA.
No uses casos complejos ni escenarios de aplicacion avanzada.
Las preguntas deben ser accesibles para un estudiante que inicia el curso.

## ESTRUCTURA DE LAS PREGUNTAS

Genera exactamente 10 preguntas de seleccion multiple con unica respuesta correcta.

Cada pregunta debe tener:
- 4 opciones de respuesta (A, B, C, D).
- Exactamente UNA respuesta correcta marcada con =.
- Tres distractores plausibles marcados con ~.
- Retroalimentacion para CADA opcion, iniciando con #Correcto. o #Incorrecto.

## DISTRIBUCION TEMATICA

Distribuye las 10 preguntas de manera equilibrada entre los cinco documentos fuente:
- 2 preguntas basadas en el documento 1.
- 2 preguntas basadas en el documento 2.
- 2 preguntas basadas en el documento 3.
- 2 preguntas basadas en el documento 4.
- 2 preguntas basadas en el documento 5.

## NIVELES COGNITIVOS

Prioriza estos niveles cognitivos en orden:
1. Recordar: identificar conceptos, terminos, definiciones.
2. Comprender: explicar relaciones basicas, diferenciar ideas.
3. Identificar: reconocer aplicaciones simples.

NO uses niveles de evaluacion, sintesis o pensamiento critico en esta prueba.

## CRITERIOS DE CALIDAD

- Cada pregunta debe ser clara, precisa y sin ambiguedades.
- Los distractores deben ser plausibles, no absurdos ni obviamente incorrectos.
- La retroalimentacion debe ser instructiva: explicar por que la opcion es correcta o incorrecta.
- No repitas conceptos entre preguntas.
- No uses la misma estructura de pregunta dos veces.
- Las preguntas deben ser independientes entre si.

## DATOS DEL CURSO

PROGRAMA: {programa}
ASIGNATURA: {asignatura}

## DOCUMENTOS FUENTE

{corpus}

Genera unicamente el contenido GIFT solicitado.
