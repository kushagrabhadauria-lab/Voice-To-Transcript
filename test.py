from hubspot_util import HubSpotClient, HUBSPOT_TOKEN

def get_company_id_from_call_id(hubspot_client: HubSpotClient, call_id):
    try:
        associations = hubspot_client.client.crm.associations.v4.basic_api.get_page(
            object_type="calls",
            object_id=call_id,
            to_object_type="companies",
            limit=1
        )

        if associations.results:
            company_id = associations.results[0].to_object_id
            print("Company ID:", company_id)
            company = hubspot_client.client.crm.companies.basic_api.get_by_id(
            company_id=company_id,
            properties=["name", "sentiment_score_1"]
            )

            # hubspot_client.client.crm.companies.basic_api.update(
            # company_id=company_id,
            # simple_public_object_input={
            #     "properties": {
            #         "sentiment_score_1": "10"
            #     }
            # }
        # )

        return {
            "company_id": company_id,
            "properties_name": company.properties
        }
    
    except Exception as e:
        print("HubSpot API error:", e)

if __name__ == "__main__":
    hubspot_client = HubSpotClient(HUBSPOT_TOKEN)
    print(get_company_id_from_call_id(hubspot_client, "287884265186"))

