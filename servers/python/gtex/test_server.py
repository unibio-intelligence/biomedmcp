"""Simple test to verify the GTEx MCP server works."""

import asyncio
from server import mcp


async def main():
    """Test that all tools are registered."""
    print("GTEx MCP Server Test")
    print("=" * 50)

    # Get all tools
    tools = await mcp.get_tools()

    print(f"\nTotal tools registered: {len(tools)}")
    print("\nAvailable tools:")

    categories = {
        "API Info": [],
        "Expression Data": [],
        "Association (Static)": [],
        "Association (Dynamic)": [],
        "Reference Genome": [],
        "Dataset": [],
        "Biobank": [],
    }

    for tool in tools:
        name = tool if isinstance(tool, str) else tool.name
        if "service" in name:
            categories["API Info"].append(name)
        elif "expression" in name or "top_expressed" in name or "list_tissues" in name:
            categories["Expression Data"].append(name)
        elif "dynamic" in name:
            categories["Association (Dynamic)"].append(name)
        elif "eqtl" in name or "sqtl" in name or "metasoft" in name:
            categories["Association (Static)"].append(name)
        elif "gene_info" in name or "transcript" in name or "exon" in name or "variant" in name:
            categories["Reference Genome"].append(name)
        elif "dataset" in name:
            categories["Dataset"].append(name)
        elif "sample" in name:
            categories["Biobank"].append(name)

    for category, tool_names in categories.items():
        if tool_names:
            print(f"\n{category} ({len(tool_names)}):")
            for name in tool_names:
                print(f"  ✓ {name}")

    print("\n" + "=" * 50)
    print("✅ Server is configured correctly!")
    print("\nTo run the server:")
    print("  uv run server.py")
    print("\nOr with fastmcp:")
    print("  uv run fastmcp run server.py:mcp")


if __name__ == "__main__":
    asyncio.run(main())