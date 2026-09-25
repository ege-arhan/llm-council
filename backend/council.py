"""3-stage LLM Council orchestration."""

from typing import List, Dict, Any, Tuple
from .openrouter import query_models_parallel, query_model
from .config import CHAIRMAN_MODEL, COUNCIL_MAX_REVIEWERS
from .models import resolve_council_models


def contextualize_query(messages: List[Dict[str, Any]], question: str) -> str:
    """Give follow-up questions the last completed turns without unbounded history."""
    turns = []
    for message in messages:
        if message.get("role") == "user" and message.get("content"):
            turns.append(f"User: {message['content']}")
        elif message.get("role") == "assistant" and message.get("stage3", {}).get("response"):
            turns.append(f"Council: {message['stage3']['response']}")
    prior = "\n\n".join(turns[-6:])[-6000:]
    return f"Earlier conversation:\n{prior}\n\nCurrent question:\n{question}" if prior else question


def mark_partial_council(stage3: Dict[str, Any], configured_count: int, answers_count: int, reviews_count: int) -> Dict[str, Any]:
    if answers_count < configured_count or (answers_count >= 2 and reviews_count < min(answers_count, COUNCIL_MAX_REVIEWERS)):
        stage3["degraded"] = True
        stage3.setdefault("reason", "Bazı Council üyeleri yanıt veya değerlendirme veremedi; sonuç kısmi katılımla üretildi.")
    return stage3


def response_label(index: int) -> str:
    label = ""
    while True:
        index, digit = divmod(index, 26)
        label = chr(65 + digit) + label
        if index == 0:
            return label
        index -= 1


def select_reviewers(stage1_results: List[Dict[str, Any]]) -> List[str]:
    """Review with a bounded, provider-diverse panel after every member answers."""
    selected = []
    families = set()
    for item in stage1_results:
        model = item["model"]
        family = model.split("/", 1)[0]
        if family not in families:
            selected.append(model)
            families.add(family)
            if len(selected) >= COUNCIL_MAX_REVIEWERS:
                return selected
    for item in stage1_results:
        model = item["model"]
        if model not in selected:
            selected.append(model)
            if len(selected) >= COUNCIL_MAX_REVIEWERS:
                break
    return selected


async def stage1_collect_responses(user_query: str, models: List[str] | None = None) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    messages = [{"role": "system", "content": "Answer substantively but concisely. State material assumptions and uncertainty. Do not invent sources or add filler."}, {"role": "user", "content": user_query}]

    # Query all models in parallel
    responses = await query_models_parallel(models or await resolve_council_models(), messages, max_tokens=900)

    # Format results
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', '')
            })

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [response_label(i) for i in range(len(stage1_results))]

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    if len(stage1_results) < 2:
        return [], label_to_model

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response'][:1600]}"
        for label, result in zip(labels, stage1_results)
    ])

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. Identify factual errors and material disagreements. Briefly explain the strongest and weakest responses.
2. Then, at the very end of your response, provide a final ranking of ALL responses.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # The full roster answers independently; a bounded, diverse subset reviews.
    responses = await query_models_parallel(select_reviewers(stage1_results), messages, max_tokens=650)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    chairman_model: str | None = None,
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response'][:2400]}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking'][:1200]}"
        for result in stage2_results
    ])

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    candidates = list(dict.fromkeys([chairman_model or CHAIRMAN_MODEL or stage1_results[0]["model"]]
                                    + [item["model"] for item in stage1_results]))[:3]
    for model in candidates:
        response = await query_model(model, messages, max_tokens=2200)
        if response and response.get("content"):
            return {"model": model, "response": response["content"], "degraded": model != candidates[0]}

    # Preserve a real answer when every synthesis attempt fails; label it clearly.
    return {"model": stage1_results[0]["model"], "response": stage1_results[0]["response"],
            "degraded": True, "reason": "Sentez başarısız; ilk bağımsız görüş gösteriliyor."}


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]+\b', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]+\b', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]+\b', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]+\b', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = list(dict.fromkeys(parse_ranking_from_text(ranking_text)))

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    # Avoid an extra model call for a cosmetic label on every new conversation.
    title = " ".join(user_query.split()).strip('"\'') or "New Conversation"
    return title[:47] + "..." if len(title) > 50 else title


async def run_full_council(user_query: str) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process.

    Args:
        user_query: The user's question

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses
    models = await resolve_council_models()
    stage1_results = await stage1_collect_responses(user_query, models)

    # An empty council must not be saved as a completed answer.
    if not stage1_results:
        raise RuntimeError("Tüm Council modelleri başarısız oldu; yanıt üretilmedi.")

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results)

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        CHAIRMAN_MODEL or models[0],
    )
    mark_partial_council(stage3_result, len(models), len(stage1_results), len(stage2_results))

    # Prepare metadata
    metadata = {
        "configured_models": models,
        "reviewer_models": select_reviewers(stage1_results) if len(stage1_results) >= 2 else [],
        "stage1_failed_models": [model for model in models if model not in {item["model"] for item in stage1_results}],
        "stage2_failed_models": [model for model in (select_reviewers(stage1_results) if len(stage1_results) >= 2 else []) if model not in {rank["model"] for rank in stage2_results}],
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings
    }

    return stage1_results, stage2_results, stage3_result, metadata
