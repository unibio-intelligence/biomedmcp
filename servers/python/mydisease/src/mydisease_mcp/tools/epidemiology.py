"""Epidemiology and demographic tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


class EpidemiologyApi:
    """Tools for epidemiological data."""
    
    async def get_disease_prevalence(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        population: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get prevalence data for a disease."""
        params = {
            "fields": "prevalence,epidemiology,orphanet.prevalence"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        prevalence_data = {
            "disease_id": disease_id,
            "global_prevalence": None,
            "prevalence_by_region": [],
            "prevalence_by_population": [],
            "orphanet_prevalence": None
        }
        
        # Extract general prevalence
        if "prevalence" in result:
            prev = result["prevalence"]
            if isinstance(prev, dict):
                prevalence_data["global_prevalence"] = prev
            elif isinstance(prev, list):
                for p in prev:
                    if population is None or p.get("population") == population:
                        if p.get("region"):
                            prevalence_data["prevalence_by_region"].append(p)
                        else:
                            prevalence_data["prevalence_by_population"].append(p)
        
        # Extract epidemiology data
        if "epidemiology" in result:
            epi = result["epidemiology"]
            epi = epi if isinstance(epi, list) else [epi]
            
            for e in epi:
                if "prevalence" in e:
                    prevalence_data["prevalence_by_region"].append({
                        "region": e.get("region"),
                        "prevalence": e.get("prevalence"),
                        "incidence": e.get("incidence"),
                        "year": e.get("year"),
                        "source": e.get("source")
                    })
        
        # Extract Orphanet prevalence
        if "orphanet" in result and "prevalence" in result["orphanet"]:
            orph_prev = result["orphanet"]["prevalence"]
            prevalence_data["orphanet_prevalence"] = {
                "prevalence_class": orph_prev.get("prevalence_class"),
                "prevalence_geographic": orph_prev.get("prevalence_geographic"),
                "prevalence_qualification": orph_prev.get("prevalence_qualification"),
                "prevalence_type": orph_prev.get("prevalence_type"),
                "prevalence_validation": orph_prev.get("prevalence_validation")
            }
        
        return {
            "success": True,
            "prevalence_data": prevalence_data,
            "population_filter": population
        }
    
    async def get_disease_incidence(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        time_period: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get incidence data for a disease."""
        params = {
            "fields": "incidence,epidemiology,orphanet.incidence"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        incidence_data = {
            "disease_id": disease_id,
            "annual_incidence": [],
            "incidence_trends": [],
            "age_specific_incidence": []
        }
        
        # Extract incidence data
        if "incidence" in result:
            inc = result["incidence"]
            inc = inc if isinstance(inc, list) else [inc]
            
            for i in inc:
                if time_period is None or i.get("period") == time_period:
                    if i.get("age_group"):
                        incidence_data["age_specific_incidence"].append(i)
                    else:
                        incidence_data["annual_incidence"].append(i)
        
        # Extract from epidemiology
        if "epidemiology" in result:
            epi = result["epidemiology"]
            epi = epi if isinstance(epi, list) else [epi]
            
            for e in epi:
                if "incidence" in e:
                    incidence_data["annual_incidence"].append({
                        "incidence": e.get("incidence"),
                        "year": e.get("year"),
                        "region": e.get("region"),
                        "per_population": e.get("per_population", 100000)
                    })
        
        # Calculate trends if multiple years available
        yearly_data = {}
        for inc in incidence_data["annual_incidence"]:
            if inc.get("year"):
                year = inc["year"]
                if year not in yearly_data:
                    yearly_data[year] = []
                yearly_data[year].append(inc)
        
        if len(yearly_data) > 1:
            years = sorted(yearly_data.keys())
            for i in range(len(years) - 1):
                year1, year2 = years[i], years[i + 1]
                if yearly_data[year1] and yearly_data[year2]:
                    incidence_data["incidence_trends"].append({
                        "period": f"{year1}-{year2}",
                        "trend": "increasing/decreasing",  # Would calculate from data
                        "change_percent": None  # Would calculate
                    })
        
        return {
            "success": True,
            "incidence_data": incidence_data,
            "time_period_filter": time_period
        }
    
    async def get_demographic_data(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get demographic information for a disease."""
        params = {
            "fields": "demographics,age_of_onset,sex_ratio,ethnicity,orphanet.age_of_onset"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        demographics = {
            "disease_id": disease_id,
            "age_of_onset": None,
            "sex_distribution": None,
            "ethnic_distribution": [],
            "affected_populations": []
        }
        
        # Extract demographics
        if "demographics" in result:
            demo = result["demographics"]
            demographics.update(demo)
        
        # Extract age of onset
        if "age_of_onset" in result:
            demographics["age_of_onset"] = result["age_of_onset"]
        elif "orphanet" in result and "age_of_onset" in result["orphanet"]:
            onset = result["orphanet"]["age_of_onset"]
            onset = onset if isinstance(onset, list) else [onset]
            demographics["age_of_onset"] = [o.get("label") for o in onset]
        
        # Extract sex ratio
        if "sex_ratio" in result:
            demographics["sex_distribution"] = result["sex_ratio"]
        
        # Extract ethnicity data
        if "ethnicity" in result:
            eth = result["ethnicity"]
            eth = eth if isinstance(eth, list) else [eth]
            demographics["ethnic_distribution"] = eth
        
        return {
            "success": True,
            "demographics": demographics
        }
    
    async def get_geographic_distribution(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get geographic distribution of a disease."""
        params = {
            "fields": "geographic_distribution,prevalence,epidemiology"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        distribution = {
            "disease_id": disease_id,
            "regions": [],
            "endemic_areas": [],
            "global_distribution": None
        }
        
        # Extract geographic distribution
        if "geographic_distribution" in result:
            geo = result["geographic_distribution"]
            geo = geo if isinstance(geo, list) else [geo]
            
            for g in geo:
                if region is None or g.get("region") == region:
                    distribution["regions"].append({
                        "region": g.get("region"),
                        "country": g.get("country"),
                        "prevalence": g.get("prevalence"),
                        "status": g.get("status", "present")
                    })
        
        # Extract from prevalence data
        if "prevalence" in result:
            prev = result["prevalence"]
            prev = prev if isinstance(prev, list) else [prev]
            
            for p in prev:
                if p.get("region") or p.get("country"):
                    if region is None or p.get("region") == region:
                        distribution["regions"].append({
                            "region": p.get("region"),
                            "country": p.get("country"),
                            "prevalence": p.get("value"),
                            "prevalence_type": p.get("type")
                        })
        
        # Identify endemic areas
        for r in distribution["regions"]:
            if r.get("status") == "endemic" or (r.get("prevalence") and 
                                                 isinstance(r["prevalence"], (int, float)) and 
                                                 r["prevalence"] > 0.01):  # >1% prevalence
                distribution["endemic_areas"].append(r["region"] or r["country"])
        
        return {
            "success": True,
            "geographic_distribution": distribution,
            "region_filter": region
        }


EPIDEMIOLOGY_TOOLS = [
    types.Tool(
        name="get_disease_prevalence",
        description="Get prevalence data for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "population": {
                    "type": "string",
                    "description": "Filter by population group"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_disease_incidence",
        description="Get incidence data and trends for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "time_period": {
                    "type": "string",
                    "description": "Filter by time period"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_demographic_data",
        description="Get demographic information (age, sex, ethnicity) for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_geographic_distribution",
        description="Get geographic distribution and endemic areas",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "region": {
                    "type": "string",
                    "description": "Filter by region"
                }
            },
            "required": ["disease_id"]
        }
    )
]